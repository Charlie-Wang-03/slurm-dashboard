"""get_active_jobs_status: current-user squeue query + status mapping.

Locks the subprocess contract — `squeue -u <current user> -h -o "%i|%T"` —
so the Jobs page active queue can never silently regress to a cluster-wide
query. subprocess.run is mocked; no real SLURM required.
"""

from unittest.mock import patch

from app.config import CURRENT_USER
from app.slurm import get_active_jobs_status


class FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_active_jobs_queries_current_user_only():
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        return FakeCompleted(stdout="12345|RUNNING\n12346|PENDING\n")

    with patch("app.slurm.subprocess.run", side_effect=fake_run):
        status = get_active_jobs_status()

    # The active queue must be scoped to the current Unix user, matching
    # what the UI, README and i18n copy promise ("squeue -u $USER").
    assert captured["args"] == ["squeue", "-u", CURRENT_USER, "-h", "-o", "%i|%T"]

    assert status == {"12345": "Running", "12346": "Pending"}


def test_active_jobs_failure_returns_empty():
    with patch(
        "app.slurm.subprocess.run",
        return_value=FakeCompleted(returncode=1, stderr="squeue: error"),
    ):
        assert get_active_jobs_status() == {}
