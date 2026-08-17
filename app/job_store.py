"""Job records persistence (v2 schema)."""

from dataclasses import asdict
from typing import Dict, List, Optional

from app.database import get_connection, init_db
from app.models import JobRecord


def row_to_dict(row) -> Dict:
    return dict(row)


def create_job(record: JobRecord) -> None:
    init_db()
    data = asdict(record)
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    values = list(data.values())

    with get_connection() as conn:
        conn.execute(
            f"INSERT INTO jobs ({columns}) VALUES ({placeholders})",
            values,
        )


def list_jobs(limit: Optional[int] = None, offset: int = 0) -> List[Dict]:
    """Page job records, newest first."""
    init_db()
    with get_connection() as conn:
        if limit is not None:
            rows = conn.execute(
                """
                SELECT *
                FROM jobs
                ORDER BY submit_time DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM jobs
                ORDER BY submit_time DESC, id DESC
                """
            ).fetchall()
    return [row_to_dict(row) for row in rows]


def count_jobs() -> int:
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    return row[0] if row else 0


def get_jobs_by_ids(job_ids: List[str]) -> List[Dict]:
    if not job_ids:
        return []
    init_db()
    placeholders = ", ".join(["?"] * len(job_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM jobs
            WHERE job_id IN ({placeholders})
            ORDER BY submit_time DESC, id DESC
            """,
            job_ids,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_job_by_job_id(job_id: str) -> Optional[Dict]:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return row_to_dict(row)


def update_job_status(job_id: str, status: str) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?
            WHERE job_id = ?
            """,
            (status, job_id),
        )


def mark_cancelled(job_id: str) -> None:
    update_job_status(job_id, "CANCELLED")


def get_known_job_ids() -> set:
    init_db()
    with get_connection() as conn:
        rows = conn.execute("SELECT job_id FROM jobs").fetchall()
    return {str(row["job_id"]) for row in rows if row["job_id"]}
