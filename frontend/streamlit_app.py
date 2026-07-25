"""
streamlit_app.py — Single-page Streamlit frontend for the GCP Compliance Agent.

Sends natural language queries to the FastAPI backend and renders
the agent's markdown response in the browser.
"""

import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="GCP Compliance Agent",
    page_icon="🔍",
    layout="centered",
)

st.title("🔍 GCP Pipeline Compliance Agent")
st.caption(
    "Powered by Gemini 2.5 Flash · Deployed on Cloud Run · "
    "Monitoring simulated GCP pipeline"
)
st.divider()

st.info(
    '💡 Try asking:  "Why did my pipeline fail last night?"  |  '
    '"Is my pipeline SOC 2 compliant this week?"  |  "Give me a full audit report"'
)

query = st.text_area(
    "Your question",
    placeholder=(
        "Ask about your pipeline health, compliance status, "
        "or request an audit report..."
    ),
    height=100,
)

col1, col2 = st.columns([1, 4])

with col1:
    submitted = st.button("Ask Agent", type="primary")

if submitted:
    if not query.strip():
        st.warning("Please enter a question before submitting.")
    else:
        with st.spinner("Agent is thinking..."):
            try:
                resp = requests.post(
                    f"{BACKEND_URL}/chat",
                    json={"query": query},
                    timeout=60,
                )
                resp.raise_for_status()
                result = resp.json()

                st.divider()
                st.markdown("### Agent Response")
                st.markdown(result["response"])

                if result.get("tools_called"):
                    st.info(
                        f"🔧 Tools used: {', '.join(result['tools_called'])}"
                    )

            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to backend. Is it running?")
            except Exception as exc:
                st.error(f"Error: {str(exc)}")

st.divider()
st.caption(
    "GCP DevOps Compliance Agent · GitHub: Xaaby/gcp-devops-compliance-agent"
)
