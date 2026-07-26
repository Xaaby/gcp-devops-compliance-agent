# GCP DevOps Compliance Agent

> A GCP-native AI agent that monitors a simulated data pipeline, detects compliance failures, and answers natural language questions about pipeline health — deployed on Cloud Run with Gemini 2.5 Flash.

**Live demo:** [Frontend](https://gcp-devops-frontend-786562162192.us-central1.run.app/) · [Backend /health — URL after deploy]  
**Stack:** Python 3.11 · FastAPI · Streamlit · Gemini 2.5 Flash · Cloud Run · GitHub Actions

---

## Architecture

```
User
 │
 ▼
Streamlit Frontend (Cloud Run · port 8080)
 │  POST /chat  {"query": "..."}
 ▼
FastAPI Backend (Cloud Run · port 8080)
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

**Simulated pipeline data:** 1,011 SQLite rows (7 days × 3 services, every 30 min) with 3 injected anomalies 5 hours ago — Cloud Functions OOM, BigQuery timeout, Pub/Sub backlog spike. All three are unacknowledged, triggering a SOC 2 SLA breach.

---

## Demo Queries

| Query | Tools Fired | What It Shows |
|---|---|---|
| "Why did my pipeline fail last night?" | `get_pipeline_health` | Anomaly detection + root cause |
| "Is my pipeline SOC 2 compliant this week?" | `check_compliance` → `generate_audit_report` | Compliance scoring + violation list |
| "Give me a full audit report" | All three in sequence | Full ReAct reasoning chain |
| "What were the IAM violations in the last 7 days?" | `check_compliance` | NIST IAM control enforcement |

---

## GCP Services Used

| Service | Purpose |
|---|---|
| Cloud Run | Hosts both backend and frontend containers |
| Artifact Registry | Stores Docker images (`gcp-devops-agent` repo) |
| Secret Manager | Stores `GEMINI_API_KEY` — never in env vars or source |
| Cloud Build | Triggered by GitHub Actions to build and push images |
| Cloud Logging | Receives structured JSON logs from the backend |
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
  └── Authenticate to GCP via Workload Identity Federation (no long-lived keys)
        └── Cloud Build
              ├── Build backend Docker image → push to Artifact Registry
              ├── Deploy backend to Cloud Run (us-central1)
              ├── Build frontend Docker image → push to Artifact Registry
              └── Deploy frontend to Cloud Run (us-central1)
```

Authentication uses **Workload Identity Federation** — GitHub OIDC token is exchanged for a short-lived GCP credential. No service account JSON keys are stored in GitHub Secrets.

---

## Compliance Rules (what `check_compliance` enforces)

| Rule | Control | Penalty |
|---|---|---|
| `LOGGING_COMPLETENESS` | SOC 2 CC7.2 — every run must produce a log entry | −10 per missing run |
| `FAILURE_ACKNOWLEDGMENT_SLA` | SOC 2 CC7.3 — failures acknowledged within 4 hours | −20 per breach |
| `IAM_SCOPE` | NIST AC-6 — no over-privileged IAM on pipeline runs | −15 per violation |

Score starts at 100. Status: **COMPLIANT** (≥80) · **AT_RISK** (60–79) · **NON_COMPLIANT** (<60).

The 3 injected anomalies are all unacknowledged — this drives a score of ~40/100 (NON_COMPLIANT) in any demo query covering the last 7 days.

---

## Production Considerations

This project uses simulated SQLite data to keep the demo self-contained and free-tier safe. The architecture is designed so that moving to real GCP infrastructure requires changing **only the data layer** — the agent, tools, and deployment are production-ready as-is.

### Cold start mitigation
The backend Cloud Run service runs with `--min-instances=1`. Without this, the first request after idle triggers a ~4–6 second container cold start before Gemini even receives the query. With `min-instances=1`, the container stays warm and the agent responds in under 3 seconds consistently.

```bash
gcloud run services update backend \
  --region us-central1 \
  --min-instances 1
```

### Secret management
`GEMINI_API_KEY` is stored in GCP Secret Manager and mounted as an environment variable at Cloud Run deploy time — it is never written to source code, never passed as a plain env var in `deploy.yml`, and never logged. Secret rotation requires no code change: update the secret version in Secret Manager and redeploy.

### Structured observability
Every request to `/chat` emits a structured JSON log to Cloud Logging with:
- `query` — the user's question
- `tools_called` — which tools fired and in what order
- `latency_ms` — total agent response time
- `compliance_score` — if a compliance tool was invoked

This means every agent invocation is queryable in Cloud Logging with a single filter:
```
resource.type="cloud_run_revision"
jsonPayload.tools_called=~"check_compliance"
```

### Path to real GCP data
Swapping SQLite for real pipeline data requires changes to three functions only — the agent, tool schemas, and Cloud Run config stay identical:

| Current (simulated) | Production replacement |
|---|---|
| SQLite `pipeline_logs.db` | Cloud Logging API (`entries.list`) + BigQuery audit table |
| `generate_logs.py` anomaly injection | Real Cloud Functions, BigQuery, Pub/Sub log streams |
| File baked into Docker image | Cloud Run reads from BigQuery at query time |

The compliance rule engine in `check_compliance.py` is data-source agnostic — it receives a list of run records regardless of where they came from.

### IAM boundary
The Cloud Run service account (`gcp-devops-agent-sa`) holds exactly three roles. It cannot create resources, read arbitrary secrets, or invoke other services. If the container is compromised, the blast radius is limited to log writes and the one named secret.

### Scaling behavior
Cloud Run scales to zero when idle (cost: $0) and scales out horizontally under load. The Gemini API is the only stateful dependency — the backend is fully stateless and can run as many concurrent instances as Cloud Run allows without coordination overhead. SQLite is read-only and baked into the image, so concurrent reads across instances are safe.

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

No Docker required for local development. Docker is only needed for Cloud Run deployment.

---

## Repository Structure

```
gcp-devops-compliance-agent/
├── .github/workflows/deploy.yml     ← GitHub Actions CI/CD (WIF auth)
├── backend/
│   ├── main.py                      ← FastAPI app (POST /chat, GET /health)
│   ├── agent.py                     ← Gemini ReAct dispatch loop
│   ├── tools/
│   │   ├── pipeline_health.py       ← Tool 1
│   │   ├── compliance_check.py      ← Tool 2
│   │   └── audit_report.py          ← Tool 3
│   ├── data/
│   │   ├── generate_logs.py         ← Seeds pipeline_logs.db
│   │   └── pipeline_logs.db         ← Baked into Docker image
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── streamlit_app.py
│   ├── streamlit.Dockerfile
│   └── streamlit-requirements.txt
├── docker-compose.yml               ← Local dev only
└── README.md
```
