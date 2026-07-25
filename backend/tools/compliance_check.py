"""
compliance_check.py — Tool 2: Evaluate pipeline compliance against SOC 2 and NIST controls.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "data" / "pipeline_logs.db"

_SERVICES = ["cloud_functions", "bigquery", "pubsub"]
_INTERVAL_HOURS = 0.5  # expected run frequency per service
_SLA_HOURS = 4  # FAILURE_ACKNOWLEDGMENT_SLA threshold


def _parse_date(date_str: str) -> datetime:
    """Parses an ISO date string to a datetime object.

    Args:
        date_str: Date string in 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' format.

    Returns:
        Parsed datetime object.

    Raises:
        ValueError: If the string does not match either supported format.
    """
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date string: {date_str!r}")


def _parse_end_date(date_str: str) -> datetime:
    """Parses an end-date string, treating bare dates as end-of-day (23:59:59).

    This prevents bare calendar dates like '2026-07-25' from resolving to
    midnight and inadvertently excluding same-day log entries and anomalies.

    Args:
        date_str: Date string in 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' format.

    Returns:
        Parsed datetime, with time set to 23:59:59 for bare date strings.
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59
        )


def check_compliance(start_date: str, end_date: str) -> dict[str, Any]:
    """Evaluates pipeline compliance against SOC 2 and NIST controls for a date range.

    Applies three compliance rules to all pipeline runs within the specified period:
        - LOGGING_COMPLETENESS: Every expected run slot must have a log entry.
        - FAILURE_ACKNOWLEDGMENT_SLA: Failures must be acknowledged within 4 hours.
        - IAM_SCOPE: No run should have an IAM scope violation flag.

    Starting score is 100; penalties are applied per violation, floored at 0.
    Compliance status: COMPLIANT (>=80), AT_RISK (60-79), NON_COMPLIANT (<60).

    Args:
        start_date: Range start in 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' format.
        end_date: Range end in 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS' format.

    Returns:
        dict with keys:
            compliance_score (int): 0-100 score after penalties.
            compliance_status (str): 'COMPLIANT' | 'AT_RISK' | 'NON_COMPLIANT'.
            violations (list[dict]): Each violation has rule_id, run_id,
                service_name, description, remediation, and severity.
            total_runs (int): Total rows found in the date range.
            period (dict): {'start': str, 'end': str} echo of input dates.
    """
    start_dt = _parse_date(start_date)
    end_dt = _parse_end_date(end_date)
    end_date_sql = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
    now = datetime.utcnow()

    violations: list[dict[str, Any]] = []
    score = 100

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, run_id, service_name, status, error_type, error_message,
                   timestamp, acknowledged, acknowledged_at, iam_violation,
                   memory_used_mb, duration_seconds
            FROM pipeline_logs
            WHERE datetime(timestamp) BETWEEN datetime(?) AND datetime(?)
            ORDER BY timestamp ASC
            """,
            (start_date, end_date_sql),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    total_runs = len(rows)

    # -------------------------------------------------------------------------
    # Rule 1 — LOGGING_COMPLETENESS
    # Use the actual data's time span (first → last timestamp in results) so
    # that calendar date boundary effects don't cause false positives.
    # -------------------------------------------------------------------------
    if rows:
        data_start = _parse_date(rows[0]["timestamp"])
        data_end = _parse_date(rows[-1]["timestamp"])
        data_hours = max(
            (data_end - data_start).total_seconds() / 3600, _INTERVAL_HOURS
        )
    else:
        data_hours = (end_dt - start_dt).total_seconds() / 3600

    expected_per_service = round(data_hours / _INTERVAL_HOURS)
    expected_total = len(_SERVICES) * expected_per_service
    missing_blocks = max(0, expected_total - total_runs)

    if total_runs < expected_total * 0.95 and missing_blocks > 0:
        penalty = 10 * missing_blocks
        score -= penalty
        # Create one summary violation entry per service to keep list readable
        for service in _SERVICES:
            svc_rows = [r for r in rows if r["service_name"] == service]
            expected_svc = expected_per_service
            missing_svc = max(0, expected_svc - len(svc_rows))
            if missing_svc > 0:
                violations.append(
                    {
                        "rule_id": "LOGGING_COMPLETENESS",
                        "run_id": f"missing-block-{service}-summary",
                        "service_name": service,
                        "description": (
                            f"{service} is missing {missing_svc} expected log entries "
                            f"(found {len(svc_rows)}, expected {expected_svc}) "
                            f"in the period {start_date} to {end_date}."
                        ),
                        "remediation": (
                            f"Verify that {service} pipeline runs are emitting logs to "
                            "Cloud Logging. Check for silent failures, deployment gaps, "
                            "or misconfigured log sinks. Re-enable structured logging "
                            "and confirm the pipeline schedule has not drifted."
                        ),
                        "severity": "HIGH" if missing_svc > 10 else "MEDIUM",
                    }
                )

    # -------------------------------------------------------------------------
    # Rule 2 — FAILURE_ACKNOWLEDGMENT_SLA
    # Penalise FAILED or WARNING runs that remain unacknowledged past 4 hours.
    # -------------------------------------------------------------------------
    sla_cutoff = now - timedelta(hours=_SLA_HOURS)

    for row in rows:
        if row["status"] not in ("FAILED", "WARNING"):
            continue
        if row["acknowledged"]:
            continue

        try:
            row_dt = _parse_date(row["timestamp"])
        except ValueError:
            continue

        if row_dt <= sla_cutoff:
            score -= 20
            hours_overdue = (now - row_dt).total_seconds() / 3600 - _SLA_HOURS
            violations.append(
                {
                    "rule_id": "FAILURE_ACKNOWLEDGMENT_SLA",
                    "run_id": row["run_id"],
                    "service_name": row["service_name"],
                    "description": (
                        f"{row['service_name']} run {row['run_id']} has status "
                        f"{row['status']} (error: {row['error_type']}) and has been "
                        f"unacknowledged for {hours_overdue + _SLA_HOURS:.1f} hours, "
                        f"exceeding the {_SLA_HOURS}-hour SOC 2 SLA by "
                        f"{hours_overdue:.1f} hours."
                    ),
                    "remediation": (
                        f"Immediately acknowledge run {row['run_id']} in the compliance "
                        "dashboard. Investigate root cause: "
                        f"{row['error_message'] or 'see pipeline logs'}. "
                        "Add an on-call PagerDuty alert for unacknowledged failures "
                        "to prevent future SLA breaches."
                    ),
                    "severity": "HIGH",
                }
            )

    # -------------------------------------------------------------------------
    # Rule 3 — IAM_SCOPE
    # -------------------------------------------------------------------------
    for row in rows:
        if row["iam_violation"]:
            score -= 15
            violations.append(
                {
                    "rule_id": "IAM_SCOPE",
                    "run_id": row["run_id"],
                    "service_name": row["service_name"],
                    "description": (
                        f"{row['service_name']} run {row['run_id']} triggered an IAM "
                        "scope violation. The service account accessed a resource "
                        "outside its permitted scope, violating NIST AC-6 "
                        "(Least Privilege)."
                    ),
                    "remediation": (
                        f"Audit the IAM bindings for the {row['service_name']} service "
                        "account. Remove any overly broad roles (e.g., roles/editor). "
                        "Apply least-privilege roles: roles/run.invoker, "
                        "roles/logging.logWriter, roles/secretmanager.secretAccessor. "
                        "Enable VPC Service Controls to enforce resource boundaries."
                    ),
                    "severity": "HIGH",
                }
            )

    # Floor score at 0
    score = max(0, score)

    if score >= 80:
        compliance_status = "COMPLIANT"
    elif score >= 60:
        compliance_status = "AT_RISK"
    else:
        compliance_status = "NON_COMPLIANT"

    return {
        "compliance_score": score,
        "compliance_status": compliance_status,
        "violations": violations,
        "total_runs": total_runs,
        "period": {"start": start_date, "end": end_date},
    }
