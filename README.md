# GCP DevOps Compliance Agent

A GCP-native AI agent that monitors a simulated data pipeline, detects compliance failures, and answers natural language questions about pipeline health — deployed on Cloud Run with Gemini 2.5 Flash.

**Live demo:** [Frontend](https://gcp-devops-frontend-786562162192.us-central1.run.app) · [Backend /health](https://gcp-devops-backend-786562162192.us-central1.run.app/health)

**Stack:** Python 3.11 · FastAPI · Streamlit · Gemini 2.5 Flash · Cloud Run · GitHub Actions

---

## What This Is

Most compliance tooling is either dashboards or scripts. This is an agent — it reasons across tools, decides which ones to call, and synthesizes the output into a natural language answer with a full audit trail.

The pipeline simulator runs 1,011 SQLite rows (7 days × 3 services, every 30 minutes) with 3 injected anomalies — a Cloud Functions OOM, a BigQuery timeout, and a Pub/Sub backlog spike. All three are unacknowledged, which triggers a SOC 2 SLA breach and drops the compliance score to ~40/100 (NON_COMPLIANT).

---

## Architecture

```
User
 │
 ▼
Streamlit Frontend  (Cloud Run · port 8080)
 │  POST /chat  {"query": "..."}
 ▼
FastAPI Backend  (Cloud Run · port 8080)
 │
 ▼
Gemini 2.5 Flash — Manual ReAct Dispatch Loop
 │
 ├── Tool 1: get_pipeline_health(hours_back)
 │           └── SQLite query → failures + anomalies
 │
 ├── Tool 2: check_compliance(start_date, end_date)
 │           └── SOC 2 + NIST rule engine → score 0–100
 │
 └── Tool 3: generate_audit_report(start_date, end_date)
             └── Calls Tools 1 + 2 → structured report + remediations
```

The agent runs a **manual ReAct dispatch loop** — Automatic Function Calling is disabled so the full tool-call/tool-result history is preserved and visible. The agent decides which tools to invoke, in what order, and synthesizes the final answer from all tool outputs.

---

## Demo Queries

| Query | Tools Fired | What It Shows |
|---|---|---|
| "Why did my pipeline fail last night?" | `get_pipeline_health` | Anomaly detection + root cause |
| "Is my pipeline SOC 2 compliant this week?" | `check_compliance` → `generate_audit_report` | Compliance scoring + violation list |
| "Give me a full audit report" | All three in sequence | Full ReAct reasoning chain |
| "What were the IAM violations in the last 7 days?" | `check_compliance` | NIST IAM control enforcement |

---

## Compliance Rules

| Rule | Framework Control | Score Penalty |
|---|---|---|
| LOGGING_COMPLETENESS | SOC 2 CC7.2 — every run must produce a log entry | −10 per missing run |
| FAILURE_ACKNOWLEDGMENT_SLA | SOC 2 CC7.3 — failures acknowledged within 4 hours | −20 per breach |
| IAM_SCOPE | NIST AC-6 — no over-privileged IAM on pipeline runs | −15 per violation |

Score starts at 100. Status bands: **COMPLIANT** (≥80) · **AT_RISK** (60–79) · **NON_COMPLIANT** (<60).

The 3 injected anomalies are all unacknowledged — this drives a score of ~40/100 in any query covering the last 7 days.

---

## GCP Services

| Service | Purpose |
|---|---|
| Cloud Run | Hosts backend (FastAPI) and frontend (Streamlit) as separate services |
| Artifact Registry | Stores Docker images (`gcp-devops-agent` repo, us-central1) |
| Secret Manager | Stores `GEMINI_API_KEY` — never hardcoded, never in env vars |
| Cloud Build | Triggered by GitHub Actions to build and push images |
| Cloud Logging | Receives structured JSON logs from the backend on every `/chat` call |
| IAM | One service account (`gcp-devops-agent-sa`) with 3 roles only |

**Service account roles (least-privilege):**
- `roles/run.invoker`
- `roles/logging.logWriter`
- `roles/secretmanager.secretAccessor`

---

## CI/CD Pipeline

Every push to `main` triggers:

```
GitHub Actions
  └── Authenticate via Workload Identity Federation (no long-lived keys)
        └── Cloud Build
              ├── Build backend image → push to Artifact Registry
              ├── Deploy backend to Cloud Run (us-central1)
              ├── Build frontend image → push to Artifact Registry
              └── Deploy frontend to Cloud Run (us-central1)
```

Authentication uses **Workload Identity Federation** — GitHub OIDC token is exchanged for a short-lived GCP credential. No service account JSON keys are stored anywhere.

---

## Observability

Every `/chat` request emits a structured JSON log to Cloud Logging:

```json
{
  "query": "Give me a full audit report",
  "tools_called": ["get_pipeline_health", "check_compliance", "generate_audit_report"],
  "latency_ms": 2847,
  "compliance_score": 40
}
```

Queryable in Cloud Logging with a single filter:
```
resource.type="cloud_run_revision"
jsonPayload.tools_called=~"check_compliance"
```

---

## Path to Real GCP Data

This project uses SQLite to stay self-contained and free-tier safe. Moving to real infrastructure requires changes to the data layer only — the agent, tools, and deployment are production-ready as-is.

| Current (simulated) | Production replacement |
|---|---|
| `SQLite pipeline_logs.db` | Cloud Logging API (`entries.list`) + BigQuery audit table |
| `generate_logs.py` anomaly injection | Real Cloud Functions, BigQuery, Pub/Sub log streams |
| File baked into Docker image | Cloud Run reads from BigQuery at query time |

The compliance rule engine in `check_compliance.py` is data-source agnostic — it receives a list of run records regardless of where they came from.

---

## Repository Structure

```
gcp-devops-compliance-agent/
├── .github/workflows/deploy.yml     ← GitHub Actions CI/CD (WIF auth)
├── backend/
│   ├── main.py                      ← FastAPI app (POST /chat, GET /health)
│   ├── agent.py                     ← Gemini ReAct dispatch loop
│   ├── tools/
│   │   ├── pipeline_health.py       ← Tool 1: get_pipeline_health
│   │   ├── compliance_check.py      ← Tool 2: check_compliance
│   │   └── audit_report.py          ← Tool 3: generate_audit_report
│   ├── data/
│   │   ├── generate_logs.py         ← Seeds pipeline_logs.db
│   │   └── pipeline_logs.db         ← Baked into Docker image at build
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── streamlit_app.py
│   ├── streamlit.Dockerfile
│   └── streamlit-requirements.txt
├── docker-compose.yml               ← Local dev only
└── README.md
```

---

## Local Development

```bash
# Generate the SQLite database
cd backend/data && python generate_logs.py

# Start backend
cd backend && uvicorn main:app --reload --port 8000

# Start frontend (separate terminal)
cd frontend && BACKEND_URL=http://localhost:8000 streamlit run streamlit_app.py
```

No Docker required locally. Docker is used only for Cloud Run deployment.

---

## Cold Start Note

The backend runs with `--min-instances=1` so the container stays warm. Without it, the first request after idle triggers a 4–6 second cold start before Gemini receives the query. With a warm instance, agent responses consistently come back under 3 seconds.
