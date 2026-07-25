"""
Streamlit frontend for GCP DevOps Compliance Agent.
Calls FastAPI backend /chat endpoint and renders agent response with
visible tool reasoning chain — so the agent's decision-making is observable.
"""

import os
import streamlit as st
import requests

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

TOOL_META: dict[str, dict[str, str]] = {
    "get_pipeline_health": {
        "label": "Pipeline Health",
        "icon": "🔍",
        "description": "Queried pipeline logs for failures and anomalies",
    },
    "check_compliance": {
        "label": "Compliance Check",
        "icon": "🛡️",
        "description": "Evaluated runs against SOC 2 / NIST controls",
    },
    "generate_audit_report": {
        "label": "Audit Report",
        "icon": "📋",
        "description": "Generated structured compliance summary with remediations",
    },
}

DEMO_QUERIES: list[str] = [
    "Why did my pipeline fail last night?",
    "Is my pipeline SOC 2 compliant this week?",
    "Give me a full audit report",
    "What were the IAM violations in the last 7 days?",
]

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="GCP Compliance Agent",
    page_icon="🤖",
    layout="centered",
)

# Minimal CSS — clean terminal-adjacent feel appropriate for a DevOps tool
st.markdown(
    """
    <style>
        /* Tighten default Streamlit padding */
        .block-container { padding-top: 2rem; padding-bottom: 2rem; }

        /* Tool chain badge row */
        .tool-chain {
            display: flex;
            align-items: center;
            gap: 6px;
            flex-wrap: wrap;
            margin-bottom: 0.75rem;
        }
        .tool-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            background: #1e2736;
            border: 1px solid #2d3f55;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 0.78rem;
            color: #7dd3fc;
            font-family: monospace;
        }
        .tool-arrow {
            color: #4b5563;
            font-size: 0.9rem;
        }
        .tool-header {
            font-size: 0.72rem;
            color: #6b7280;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            margin-bottom: 4px;
            font-family: monospace;
        }
        /* Response container */
        .response-box {
            background: #0f1923;
            border: 1px solid #1e2736;
            border-radius: 8px;
            padding: 1.2rem 1.4rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("## 🤖 GCP DevOps Compliance Agent")
st.markdown(
    "Powered by **Gemini 2.5 Flash** · Deployed on **Cloud Run** · "
    "Monitors Cloud Functions, BigQuery, and Pub/Sub"
)
st.divider()

# ── Demo query buttons ────────────────────────────────────────────────────────

st.markdown("**Try a demo query:**")
cols = st.columns(2)
selected_demo: str | None = None

for i, query in enumerate(DEMO_QUERIES):
    if cols[i % 2].button(query, use_container_width=True):
        selected_demo = query

st.divider()

# ── Main input ────────────────────────────────────────────────────────────────

query_input = st.text_input(
    label="Ask the agent",
    value=selected_demo or "",
    placeholder="Ask about your pipeline...",
    label_visibility="collapsed",
)

ask_clicked = st.button("Ask Agent", type="primary", use_container_width=True)

# ── Agent call + response rendering ───────────────────────────────────────────

if ask_clicked and query_input.strip():
    with st.spinner("Agent is reasoning..."):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/chat",
                json={"query": query_input.strip()},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()

        except requests.exceptions.ConnectionError:
            st.error(
                f"Cannot reach backend at `{BACKEND_URL}`. "
                "Is the FastAPI server running?"
            )
            st.stop()

        except requests.exceptions.Timeout:
            st.error("Agent timed out after 60 seconds. Try again.")
            st.stop()

        except requests.exceptions.HTTPError as exc:
            st.error(f"Backend returned an error: {exc.response.status_code}")
            st.stop()

    agent_response: str = data.get("response", "")
    tools_called: list[str] = data.get("tools_called", [])

    # ── Tool reasoning chain ───────────────────────────────────────────────────
    if tools_called:
        st.markdown(
            '<div class="tool-header">Agent reasoning chain</div>',
            unsafe_allow_html=True,
        )

        badges_html = '<div class="tool-chain">'
        for idx, tool_name in enumerate(tools_called):
            meta = TOOL_META.get(tool_name, {"icon": "⚙️", "label": tool_name})
            badges_html += (
                f'<span class="tool-badge">'
                f'{meta["icon"]} {meta["label"]}'
                f"</span>"
            )
            if idx < len(tools_called) - 1:
                badges_html += '<span class="tool-arrow">→</span>'
        badges_html += "</div>"

        st.markdown(badges_html, unsafe_allow_html=True)

        # One-line description of what each tool did
        for tool_name in tools_called:
            meta = TOOL_META.get(tool_name)
            if meta:
                st.caption(f"{meta['icon']} **{meta['label']}** — {meta['description']}")

        st.divider()

    # ── Agent response ─────────────────────────────────────────────────────────
    if agent_response:
        st.markdown(agent_response)
    else:
        st.warning("Agent returned an empty response. Check backend logs.")

elif ask_clicked and not query_input.strip():
    st.warning("Please enter a question before clicking Ask Agent.")

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "GCP DevOps Compliance Agent · "
    "[GitHub](https://github.com/Xaaby/gcp-devops-compliance-agent) · "
    "Built with Gemini 2.5 Flash + FastAPI + Cloud Run"
)
