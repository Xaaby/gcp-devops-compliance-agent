"""
pipeline_health.py — Tool 1: Query recent pipeline failures and warnings from SQLite.
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "data" / "pipeline_logs.db"


def get_pipeline_health(hours_back: int) -> dict[str, Any]:
    """Retrieves pipeline failures and warnings for the last N hours.

    Queries pipeline_logs.db for FAILED or WARNING status entries within the
    specified lookback window, ordered by most recent first.

    Args:
        hours_back: Number of hours to look back from current UTC time.
                    Use 2 for "recent", 24 for "last night", 168 for "last week".

    Returns:
        dict with keys:
            failures (list[dict]): Each entry contains run_id, service_name,
                error_type, error_message, timestamp, status, memory_used_mb,
                and acknowledged flag.
            total_failures (int): Total count of matching entries.
            window_hours (int): The hours_back value used in the query.
            queried_at (str): ISO timestamp of query execution time.
    """
    queried_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    failures: list[dict[str, Any]] = []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_id, service_name, error_type, error_message,
                   timestamp, status, memory_used_mb, acknowledged
            FROM pipeline_logs
            WHERE datetime(timestamp) >= datetime('now', ?)
              AND status IN ('FAILED', 'WARNING')
            ORDER BY timestamp DESC
            """,
            (f"-{hours_back} hours",),
        )
        rows = cursor.fetchall()
        for row in rows:
            failures.append(
                {
                    "run_id": row["run_id"],
                    "service_name": row["service_name"],
                    "error_type": row["error_type"],
                    "error_message": row["error_message"],
                    "timestamp": row["timestamp"],
                    "status": row["status"],
                    "memory_used_mb": row["memory_used_mb"],
                    "acknowledged": bool(row["acknowledged"]),
                }
            )
    finally:
        conn.close()

    return {
        "failures": failures,
        "total_failures": len(failures),
        "window_hours": hours_back,
        "queried_at": queried_at,
    }
