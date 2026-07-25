"""
agent.py — Gemini 2.5 Flash agent with manual tool dispatch loop.

Uses google-genai SDK (NOT the legacy google.generativeai package).
FunctionDeclaration uses parameters_json_schema= and AutomaticFunctionCalling
is explicitly disabled to allow manual control of the ReAct loop.
"""

import logging
import os
from typing import Any

from google import genai
from google.genai import types

from tools.pipeline_health import get_pipeline_health
from tools.compliance_check import check_compliance
from tools.audit_report import generate_audit_report

# ---------------------------------------------------------------------------
# Tool declarations
# ---------------------------------------------------------------------------

health_fn = types.FunctionDeclaration(
    name="get_pipeline_health",
    description=(
        "Retrieves pipeline failures and anomalies for the last N hours. "
        "Use for questions about errors, failures, warnings, or recent pipeline status."
    ),
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "hours_back": {
                "type": "INTEGER",
                "description": (
                    "Number of hours to look back for failures. "
                    "Use 24 for 'last night', 168 for 'last week', 2 for 'recent'."
                ),
            }
        },
        "required": ["hours_back"],
    },
)

compliance_fn = types.FunctionDeclaration(
    name="check_compliance",
    description=(
        "Evaluates pipeline compliance against SOC 2 and NIST controls for a date range. "
        "Use for questions about compliance, audits, policy violations, or SLA breaches."
    ),
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "start_date": {
                "type": "STRING",
                "description": "Start date in ISO format YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS",
            },
            "end_date": {
                "type": "STRING",
                "description": "End date in ISO format YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS",
            },
        },
        "required": ["start_date", "end_date"],
    },
)

audit_fn = types.FunctionDeclaration(
    name="generate_audit_report",
    description=(
        "Generates a complete audit report combining pipeline health and compliance status. "
        "Use when asked for a full report, summary, or overview."
    ),
    parameters_json_schema={
        "type": "OBJECT",
        "properties": {
            "start_date": {
                "type": "STRING",
                "description": "Start date in ISO format YYYY-MM-DD",
            },
            "end_date": {
                "type": "STRING",
                "description": "End date in ISO format YYYY-MM-DD",
            },
        },
        "required": ["start_date", "end_date"],
    },
)

# ---------------------------------------------------------------------------
# Tool registry and generation config
# ---------------------------------------------------------------------------

pipeline_tools = types.Tool(function_declarations=[health_fn, compliance_fn, audit_fn])

config = types.GenerateContentConfig(
    system_instruction="""You are an expert GCP DevOps Compliance Agent monitoring a data pipeline infrastructure for a regulated environment.

You have three tools:
1. get_pipeline_health: Use for questions about failures, errors, anomalies, warnings, or recent pipeline status
2. check_compliance: Use for questions about SOC 2, NIST, audit readiness, policy violations, SLA breaches, or compliance score
3. generate_audit_report: Use when asked for a full report, complete summary, or overall pipeline overview

Rules:
- ALWAYS call at least one tool before answering. Never answer from memory.
- For compliance questions, call both check_compliance AND get_pipeline_health.
- For "full report" or "audit report" questions, call generate_audit_report.
- When dates are not specified, use the last 7 days as default range.
- Format your final response in clean markdown with headers, bullet points, and clear sections.
- Always end with a "Recommended Actions" section listing specific next steps.""",
    tools=[pipeline_tools],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    temperature=0.1,
)

TOOL_MAP: dict[str, Any] = {
    "get_pipeline_health": get_pipeline_health,
    "check_compliance": check_compliance,
    "generate_audit_report": generate_audit_report,
}

# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------


def run_agent(user_query: str) -> dict[str, Any]:
    """Runs the Gemini agent with manual tool dispatch loop.

    Sends the user query to Gemini 2.5 Flash and iteratively dispatches any
    tool calls until the model produces a final text response. Each tool call
    result is fed back into the conversation history before the next model call.

    Args:
        user_query: Natural language question about pipeline health or compliance.

    Returns:
        dict with keys:
            response (str): Final markdown-formatted answer from the model.
            tools_called (list[str]): Names of all tools invoked during the turn.
            error (str | None): Error message if the agent failed, else None.
    """
    try:
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

        contents_history: list[types.Content] = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_query)],
            )
        ]
        tools_called: list[str] = []

        # Initial model call
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents_history,
            config=config,
        )

        # Manual ReAct loop: keep dispatching until no more function calls
        while True:
            candidate = response.candidates[0]
            # Append exact candidate.content — preserves thinking state
            contents_history.append(candidate.content)

            fn_call_parts = [
                part
                for part in (candidate.content.parts or [])
                if part.function_call
            ]

            if not fn_call_parts:
                break

            for part in fn_call_parts:
                fn_name: str = part.function_call.name
                fn_args: dict[str, Any] = dict(part.function_call.args)

                logging.info(f"Tool called: {fn_name} with args: {fn_args}")

                tool_fn = TOOL_MAP.get(fn_name)
                if tool_fn is None:
                    raise ValueError(f"Unknown tool requested by model: {fn_name!r}")

                tool_result = tool_fn(**fn_args)
                tools_called.append(fn_name)

                tool_response_part = types.Part.from_function_response(
                    name=fn_name,
                    response={"result": tool_result},
                )
                contents_history.append(
                    types.Content(role="user", parts=[tool_response_part])
                )

            # Continue the loop with updated history
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents_history,
                config=config,
            )

        final_text: str = response.text or ""
        return {"response": final_text, "tools_called": tools_called, "error": None}

    except Exception as exc:  # noqa: BLE001
        logging.exception("Agent error: %s", exc)
        return {"response": "", "tools_called": [], "error": str(exc)}
