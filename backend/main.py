"""
main.py — FastAPI backend for the GCP Pipeline Compliance Agent.

Endpoints:
    GET  /health  — liveness probe
    POST /chat    — natural language query routed through the Gemini agent
"""

import logging
import uvicorn
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agent import run_agent

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="GCP Compliance Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    query: str


class ChatResponse(BaseModel):
    response: str
    tools_called: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health_check() -> dict:
    """Liveness probe — returns service status and current UTC timestamp."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "gcp-compliance-agent-backend",
    }


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Routes a natural language query through the Gemini agent.

    Args:
        request: ChatRequest containing the user's query string.

    Returns:
        ChatResponse with the agent's markdown-formatted answer and
        the list of tool names called during the turn.

    Raises:
        HTTPException 400: If the query is empty.
        HTTPException 500: If the agent returns an error.
    """
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty.")

    result = run_agent(request.query)

    logging.info(
        f"Chat handled — query_length={len(request.query)} "
        f"tools_called={result['tools_called']} "
        f"response_length={len(result['response'])}"
    )

    if result["error"]:
        raise HTTPException(status_code=500, detail=result["error"])

    return ChatResponse(
        response=result["response"],
        tools_called=result["tools_called"],
    )


# ---------------------------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
