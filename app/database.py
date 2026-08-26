"""SQLite storage for slurm-dashboard.

v2 schema: a single `jobs` table with the whitelist submission fields.
The legacy schema (per-project submit records) is migrated in place when
an old database file is detected — user data is preserved, never deleted.
The legacy `operations` table is left untouched on disk.
"""

import sqlite3
from pathlib import Path

from app.config import DASHBOARD_DIR

DATABASE_PATH = (DASHBOARD_DIR / "data" / "dashboard.sqlite3").resolve()

# v2 jobs table
JOBS_COLUMNS = [
    ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    ("job_id", "TEXT NOT NULL"),
    ("job_name", "TEXT NOT NULL"),
    ("script_name", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("source", "TEXT NOT NULL DEFAULT 'external'"),
    ("submit_time", "TEXT NOT NULL"),
    ("partition", "TEXT NOT NULL"),
    ("gres", "TEXT NOT NULL"),
    ("cpus_per_task", "INTEGER NOT NULL"),
    ("mem", "TEXT NOT NULL"),
    ("time_limit", "TEXT NOT NULL"),
    ("status", "TEXT NOT NULL"),
    ("workspace_path", "TEXT NOT NULL DEFAULT ''"),
    ("output_path", "TEXT NOT NULL DEFAULT ''"),
]

# Legacy column -> v2 column mapping for data migration
LEGACY_TO_V2 = [
    ("job_id", "job_id"),
    ("job_name", "job_name"),
    ("run_file", "script_name"),
    ("submit_time", "submit_time"),
    ("partition", "partition"),
    ("gres", "gres"),
    ("cpus_per_task", "cpus_per_task"),
    ("mem", "mem"),
    ("time_limit", "time_limit"),
    ("status", "status"),
    ("project_dir", "workspace_path"),
    ("stdout_path", "output_path"),
]


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _create_jobs_table(conn: sqlite3.Connection) -> None:
    columns = ", ".join(f"{name} {decl}" for name, decl in JOBS_COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS jobs ({columns})")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_job_id ON jobs(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_submit_time ON jobs(submit_time)")


def _migrate_legacy_jobs(conn: sqlite3.Connection) -> None:
    """Rebuild the jobs table from the legacy schema, preserving records."""
    legacy_cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    v2_cols = {name for name, _ in JOBS_COLUMNS}
    if v2_cols <= legacy_cols:
        return

    conn.execute("ALTER TABLE jobs RENAME TO jobs_legacy")
    try:
        _create_jobs_table(conn)
        pairs = [(legacy, new) for legacy, new in LEGACY_TO_V2 if legacy in legacy_cols]
        selected = ", ".join(f"{legacy} AS {new}" for legacy, new in pairs)
        if pairs:
            columns = ", ".join(new for _, new in pairs)
            conn.execute(
                f"INSERT INTO jobs ({columns}) "
                f"SELECT {selected} FROM jobs_legacy WHERE job_id IS NOT NULL AND job_id != ''"
            )
    except Exception:
        conn.execute("DROP TABLE IF EXISTS jobs")
        conn.execute("ALTER TABLE jobs_legacy RENAME TO jobs")
        raise
    conn.execute("DROP TABLE jobs_legacy")


def init_db() -> None:
    with get_connection() as conn:
        existing = [row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()]
        if existing:
            _migrate_legacy_jobs(conn)
        else:
            _create_jobs_table(conn)
        # Legacy `operations` table (if any) is intentionally left as-is.


def get_database_path() -> Path:
    return DATABASE_PATH
