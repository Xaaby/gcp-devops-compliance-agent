# GCP Pipeline Compliance Agent

A GCP-native AI agent that monitors data pipeline health, detects compliance failures,
and answers natural language questions using Gemini 2.5 Flash with multi-tool reasoning.

## Problem Statement

Regulated environments — government agencies, hospitals, financial institutions — cannot
afford undetected pipeline failures. In these contexts, a missed log entry or an
unacknowledged error is not a bug: it is an audit finding that can result in regulatory
action, contract penalties, or data breach liability. This agent provides continuous
compliance monitoring across Cloud Functions, BigQuery, and Pub/Sub pipelines, surfacing
failures in plain English and scoring adherence to SOC 2 and NIST controls. It turns
raw pipeline telemetry into auditor-ready reports with zero manual intervention.

## Live Demo

- 🖥️ **Frontend:** [URL added after first deploy]
- 🔌 **Backend API:** [URL added after first deploy]/health

## Architecture

```
User Query
    │
    ▼
Streamlit Frontend (Cloud Run)
    │  HTTP POST /chat
    ▼
FastAPI Backend (Cloud Run)
    │
    ▼
Gemini 2.5 Flash Agent
    │
    ├──▶ Tool 1: get_pipeline_health()   ──▶ SQLite DB
    ├──▶ Tool 2: check_compliance()      ──▶ SQLite DB + Rule Engine
    └──▶ Tool 3: generate_audit_report() ──▶ Tools 1 + 2 Combined
    │
    ▼
Natural Language Response
```

## How the Agent Works (ReAct Loop)

1. User asks a natural language question
2. Gemini reasons about which tool(s) to call
3. Tools query the simulated pipeline database
4. Results feed back to Gemini
5. Gemini synthesizes a structured markdown response

## Agent Tools

| Tool | Triggers On | Returns |
|---|---|---|
| `get_pipeline_health` | "failed", "error", "last night", "anomaly" | Failures list, severity, timestamps |
| `check_compliance` | "SOC 2", "compliant", "audit", "violations" | Score 0–100, violation details |
| `generate_audit_report` | "full report", "summary", "overview" | Combined health + compliance report |

## Sample Queries

- `"Why did my pipeline fail last night?"` → `get_pipeline_health(hours_back=24)`
- `"Is my pipeline SOC 2 compliant this week?"` → `check_compliance` + `get_pipeline_health`
- `"Give me a full audit report"` → `generate_audit_report` (calls all 3 tools)

## GCP Services Used

| Service | Purpose |
|---|---|
| Cloud Run | Hosts backend (FastAPI) and frontend (Streamlit) |
| Artifact Registry | Stores Docker images |
| Secret Manager | Stores `GEMINI_API_KEY` securely |
| Cloud Build | CI/CD image builds |
| Cloud Logging | Structured JSON logs from backend |
| IAM | Least-privilege service account (3 roles) |

## Simulated Pipeline Data

7 days of baseline logs across Cloud Functions, BigQuery, and Pub/Sub (1,008 rows).
3 injected anomalies timestamped 5 hours ago (past the 4-hour SOC 2 SLA):

- **Cloud Functions OOM** — 289 MB used, 256 MB limit → `MemoryLimitExceeded`
- **BigQuery timeout** — 300 s query, missing partition filter → `resourcesExceeded`
- **Pub/Sub backlog spike** — 145,200 unacknowledged messages → `BacklogSpike`

All 3 are `acknowledged=0` → triggers `FAILURE_ACKNOWLEDGMENT_SLA` violations → compliance score **40/100 (NON_COMPLIANT)**.

## Local Development

```bash
cp .env.example .env          # add your GEMINI_API_KEY
cd backend/data && python generate_logs.py
cd ../.. && docker-compose up --build
# Frontend: http://localhost:8501
# Backend:  http://localhost:8000/health
```

## CI/CD Pipeline

Push to `main` → GitHub Actions → Workload Identity Federation auth →
Docker build → Artifact Registry → Cloud Run deploy (backend first, then frontend with backend URL injected as env var).

## Production Readiness Notes

In production this would connect to:
- **Real Cloud Logging API** instead of SQLite simulator
- **BigQuery** for audit report persistence and long-term trend analysis
- **VPC Service Controls** around the pipeline perimeter
- **Cloud Monitoring** alerts feeding the health checker in real time

The agent architecture (FastAPI + Gemini tool loop) is identical to what would run
against live GCP APIs — only the data source changes.

## Tech Stack

| Component | Technology | Version |
|---|---|---|
| Language | Python | 3.11 |
| Backend | FastAPI + Uvicorn | ≥0.111.0 / ≥0.29.0 |
| Frontend | Streamlit | ≥1.35.0 |
| Agent SDK | google-genai | ≥0.8.0 |
| LLM | Gemini 2.5 Flash | `gemini-2.5-flash` |
| Data | SQLite | stdlib |
| Containers | Docker | `python:3.11-slim` |
| Hosting | GCP Cloud Run | `us-central1` |
| CI/CD | GitHub Actions + WIF | keyless auth |
