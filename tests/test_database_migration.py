"""Legacy -> v2 jobs table migration tests (user data preserved)."""

import sqlite3

from app.database import JOBS_COLUMNS, _migrate_legacy_jobs, _create_jobs_table


LEGACY_SQL = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    job_name TEXT NOT NULL,
    project_dir TEXT NOT NULL,
    run_file TEXT NOT NULL,
    file_type TEXT NOT NULL,
    env_path TEXT NOT NULL,
    script_path TEXT NOT NULL,
    stdout_path TEXT NOT NULL,
    stderr_path TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    checkpoint_dir TEXT NOT NULL,
    submit_time TEXT NOT NULL,
    partition TEXT NOT NULL,
    gres TEXT NOT NULL,
    cpus_per_task INTEGER NOT NULL,
    mem TEXT NOT NULL,
    time_limit TEXT NOT NULL,
    status TEXT NOT NULL
)
"""


def _make_legacy_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(LEGACY_SQL)
    conn.execute(
        """
        INSERT INTO jobs (
            job_id, job_name, project_dir, run_file, file_type, env_path,
            script_path, stdout_path, stderr_path, output_dir, checkpoint_dir,
            submit_time, partition, gres, cpus_per_task, mem, time_limit, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "12345", "train", "/home/u/projects/p1", "run.py", "py", "/home/u/envs/base",
            "/home/u/projects/p1/slurm_scripts/train_1.sh",
            "/home/u/projects/p1/logs/train_1.out",
            "/home/u/projects/p1/logs/train_1.err",
            "/home/u/projects/p1/outputs/job_12345",
            "/home/u/projects/p1/checkpoints/job_12345",
            "2026-08-01 10:00:00", "GPU", "gpu:1", 4, "16G", "00:30:00", "COMPLETED",
        ),
    )
    return conn


def test_migrate_legacy_preserves_records():
    conn = _make_legacy_conn()
    _migrate_legacy_jobs(conn)

    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    v2_cols = {name for name, _ in JOBS_COLUMNS}
    assert v2_cols <= cols, "v2 columns must all exist after migration"
    assert "project_dir" not in cols, "legacy column should be gone"

    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 1, "records must be preserved"
    row = rows[0]
    assert row["job_id"] == "12345"
    assert row["job_name"] == "train"
    assert row["script_name"] == "run.py"
    assert row["workspace_path"] == "/home/u/projects/p1"
    assert row["output_path"] == "/home/u/projects/p1/logs/train_1.out"
    assert row["partition"] == "GPU"
    assert row["status"] == "COMPLETED"


def test_migrate_is_idempotent_on_fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_jobs_table(conn)
    _migrate_legacy_jobs(conn)  # no-op on v2 schema
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "script_name" in cols


def test_create_then_migrate_keeps_data():
    """Migrating a legacy DB that already went through init_db must not lose rows."""
    conn = _make_legacy_conn()
    _migrate_legacy_jobs(conn)
    _migrate_legacy_jobs(conn)  # second pass
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    assert len(rows) == 1
