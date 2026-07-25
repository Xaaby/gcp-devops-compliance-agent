"""
audit_report.py — Tool 3: Generate a combined pipeline health and compliance audit report.
"""

from datetime import datetime, timedelta
from typing import Any

from tools.pipeline_health import get_pipeline_health
from tools.compliance_check import check_compliance

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


def generate_audit_report(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Generates a complete audit report combining pipeline health and compliance status.

    Internally calls get_pipeline_health (last 168 hours) and check_compliance
    (for the supplied date range), then merges results into a structured report
    suitable for compliance review or executive presentation.

    Args:
        start_date: Report period start in 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' format.
                    Defaults to today minus 7 days (UTC) when not provided.
        end_date: Report period end in 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' format.
                  Defaults to today (UTC) when not provided.

    Returns:
        dict with keys:
            report_id (str): Unique identifier in format 'RPT-YYYYMMDD-HHMMSS'.
            generated_at (str): ISO timestamp of report generation.
            period (dict): {'start': str, 'end': str} echo of input dates.
            total_runs (int): Total pipeline runs in the period.
            failure_count (int): Number of FAILED/WARNING runs in last 168 hours.
            compliance_score (int): 0-100 compliance score.
            compliance_status (str): 'COMPLIANT' | 'AT_RISK' | 'NON_COMPLIANT'.
            top_violations (list): Top 5 violations ranked by severity.
            recommended_remediations (list): Deduplicated remediation action strings.
            summary_text (str): 2-3 sentence human-readable executive summary.
    """
    _now = datetime.utcnow()
    if end_date is None:
        end_date = _now.strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (_now - timedelta(days=7)).strftime("%Y-%m-%d")

    generated_at = _now.strftime("%Y-%m-%dT%H:%M:%S")
    report_id = f"RPT-{_now.strftime('%Y%m%d-%H%M%S')}"

    health = get_pipeline_health(hours_back=168)
    compliance = check_compliance(start_date=start_date, end_date=end_date)

    # Top 5 violations ranked HIGH → MEDIUM → LOW
    sorted_violations = sorted(
        compliance["violations"],
        key=lambda v: _SEVERITY_ORDER.get(v.get("severity", "LOW"), 2),
    )
    top_violations = sorted_violations[:5]

    # Deduplicated remediations preserving order
    seen: set[str] = set()
    recommended_remediations: list[str] = []
    for v in sorted_violations:
        remediation = v.get("remediation", "")
        if remediation and remediation not in seen:
            seen.add(remediation)
            recommended_remediations.append(remediation)

    # Build a concise executive summary
    failure_count = health["total_failures"]
    score = compliance["compliance_score"]
    status = compliance["compliance_status"]
    violation_count = len(compliance["violations"])
    unack_count = sum(
        1 for f in health["failures"] if not f["acknowledged"]
    )

    summary_text = (
        f"Pipeline audit for the period {start_date} to {end_date} identified "
        f"{failure_count} active failure(s) or warning(s) across Cloud Functions, "
        f"BigQuery, and Pub/Sub, with {unack_count} remaining unacknowledged. "
        f"The current compliance score is {score}/100 ({status}), driven by "
        f"{violation_count} policy violation(s) — primarily unacknowledged failures "
        f"breaching the 4-hour SOC 2 SLA. "
        f"Immediate remediation of all unacknowledged incidents is required to restore "
        f"compliance posture before the next audit window."
    )

    return {
        "report_id": report_id,
        "generated_at": generated_at,
        "period": {"start": start_date, "end": end_date},
        "total_runs": compliance["total_runs"],
        "failure_count": failure_count,
        "compliance_score": score,
        "compliance_status": status,
        "top_violations": top_violations,
        "recommended_remediations": recommended_remediations,
        "summary_text": summary_text,
    }
