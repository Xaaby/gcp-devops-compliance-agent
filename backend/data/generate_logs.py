"""
generate_logs.py — Seeds the pipeline_logs SQLite database with 7 days of
baseline pipeline data across 3 GCP services and 3 injected anomalies.

Run before building the Docker image:
    python backend/data/generate_logs.py
"""

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "pipeline_logs.db"

SERVICES = ["cloud_functions", "bigquery", "pubsub"]
INTERVAL_MINUTES = 30
DAYS_BACK = 7

CREATE_TABLE_SQL = """
    CREATE TABLE pipeline_logs (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp         TEXT NOT NULL,
        service_name      TEXT NOT NULL,
        run_id            TEXT NOT NULL,
        status            TEXT NOT NULL,
        error_type        TEXT,
        error_message     TEXT,
        duration_seconds  INTEGER NOT NULL,
        memory_used_mb    INTEGER,
        records_processed INTEGER,
        iam_violation     INTEGER NOT NULL DEFAULT 0,
        acknowledged      INTEGER NOT NULL DEFAULT 0,
        acknowledged_at   TEXT
    )
"""

INSERT_SQL = """
    INSERT INTO pipeline_logs (
        timestamp, service_name, run_id, status, error_type, error_message,
        duration_seconds, memory_used_mb, records_processed, iam_violation,
        acknowledged, acknowledged_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _service_metrics(service: str) -> tuple[int, int | None, int | None]:
    """Returns (duration_seconds, memory_used_mb, records_processed) for a service.

    Args:
        service: One of "cloud_functions", "bigquery", or "pubsub".

    Returns:
        Tuple of (duration_seconds, memory_used_mb, records_processed).
    """
    if service == "cloud_functions":
        return (
            random.randint(45, 120),
            random.randint(128, 220),
            random.randint(1000, 5000),
        )
    elif service == "bigquery":
        return (
            random.randint(60, 300),
            None,
            random.randint(10_000, 100_000),
        )
    else:  # pubsub
        return (
            random.randint(5, 30),
            None,
            random.randint(500, 50_000),
        )


_BASELINE_ERRORS: dict[str, tuple[str, str]] = {
    "cloud_functions": (
        "RuntimeError",
        "Function execution failed with unhandled exception",
    ),
    "bigquery": (
        "QueryError",
        "Query execution failed due to internal resource error",
    ),
    "pubsub": (
        "DeliveryError",
        "Message batch delivery timed out after 30s",
    ),
}


def _baseline_row(ts: datetime, service: str, index: int) -> tuple:
    """Builds a single baseline pipeline log row as an INSERT-ready tuple.

    Args:
        ts: UTC timestamp for this log entry.
        service: Service name ("cloud_functions" | "bigquery" | "pubsub").
        index: Per-service row counter used to form a unique run_id.

    Returns:
        12-element tuple matching the INSERT_SQL positional parameters.
    """
    status = "SUCCESS"
    error_type = None
    error_message = None
    acknowledged = 0
    acknowledged_at = None

    # ~2% random failures, all pre-acknowledged within 1 hour
    if random.random() < 0.02:
        status = "FAILED"
        acknowledged = 1
        ack_delta = timedelta(minutes=random.randint(10, 60))
        acknowledged_at = (ts + ack_delta).strftime("%Y-%m-%dT%H:%M:%S")
        error_type, error_message = _BASELINE_ERRORS[service]

    duration, memory, records = _service_metrics(service)

    return (
        ts.strftime("%Y-%m-%dT%H:%M:%S"),
        service,
        f"run-{service}-{index}",
        status,
        error_type,
        error_message,
        duration,
        memory,
        records,
        0,  # iam_violation — baseline runs have no IAM violations
        acknowledged,
        acknowledged_at,
    )


def _anomaly_rows(now: datetime) -> list[tuple]:
    """Returns the 3 pre-defined anomaly rows injected at NOW - 2 hours.

    Args:
        now: Current UTC datetime used to compute the anomaly timestamp.

    Returns:
        List of 3 INSERT-ready tuples for the injected anomalies.
    """
    ts = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    return [
        (
            ts,
            "cloud_functions",
            "run-cloud_functions-anom-001",
            "FAILED",
            "MemoryLimitExceeded",
            "Function exceeded memory limit: used 289MB, limit 256MB",
            90,
            289,
            2500,
            0,
            0,
            None,
        ),
        (
            ts,
            "bigquery",
            "run-bigquery-anom-001",
            "FAILED",
            "resourcesExceeded",
            "Query exceeded 300s timeout; missing partition filter on table events_raw",
            301,
            None,
            None,
            0,
            0,
            None,
        ),
        (
            ts,
            "pubsub",
            "run-pubsub-anom-001",
            "WARNING",
            "BacklogSpike",
            "Unacknowledged message backlog: 145200 messages exceeds threshold of 10000",
            15,
            None,
            145_200,
            0,
            0,
            None,
        ),
    ]


def create_database() -> None:
    """Creates and seeds the pipeline_logs SQLite database.

    Drops and recreates the pipeline_logs table (idempotent). Inserts 7 days
    of 30-minute-interval baseline logs for cloud_functions, bigquery, and
    pubsub, then appends 3 injected anomalies timestamped at NOW - 2 hours.

    Raises:
        sqlite3.Error: If any database operation fails.
    """
    random.seed(42)  # fixed seed for reproducible demo data
    now = datetime.utcnow()

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()

        # Idempotent: always start fresh
        cursor.execute("DROP TABLE IF EXISTS pipeline_logs")
        cursor.execute(CREATE_TABLE_SQL)

        # Build baseline rows: 7 days back, every 30 minutes, all 3 services
        baseline_rows: list[tuple] = []
        service_index: dict[str, int] = {svc: 0 for svc in SERVICES}

        start_time = now - timedelta(days=DAYS_BACK)
        current = start_time
        while current < now:
            for service in SERVICES:
                idx = service_index[service]
                baseline_rows.append(_baseline_row(current, service, idx))
                service_index[service] += 1
            current += timedelta(minutes=INTERVAL_MINUTES)

        cursor.executemany(INSERT_SQL, baseline_rows)
        baseline_count = len(baseline_rows)

        # Inject the 3 unacknowledged anomalies
        anomalies = _anomaly_rows(now)
        cursor.executemany(INSERT_SQL, anomalies)

        conn.commit()
        total: int = cursor.execute(
            "SELECT COUNT(*) FROM pipeline_logs"
        ).fetchone()[0]
    finally:
        conn.close()

    print(
        f"Created pipeline_logs.db with {total} rows "
        f"({baseline_count} baseline + 3 anomalies)"
    )


if __name__ == "__main__":
    create_database()
