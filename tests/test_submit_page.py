"""Regression tests for the /submit page (Phase 3 newcomer UX findings).

F-1: GET /submit must render 200 in every language, never a 500. The
template formats the subtitle with ``partition_flag`` (the router's
context key); a stale ``partition=`` format name crashed the page with
``KeyError: partition_flag``.

The submit-error flow is covered too: when ``sbatch`` fails (e.g. the
binary is missing), the POST must land on a readable error page via a
303 redirect — never a 500. No SLURM job is ever submitted here; the
submit function is monkeypatched.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.slurm import SlurmSubmitError


@pytest.fixture()
def submit_client(monkeypatch, tmp_path):
    """TestClient with a configured workspace and an isolated database."""
    monkeypatch.setattr("app.config.WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr("app.database.DATABASE_PATH", tmp_path / "test.sqlite3")
    with TestClient(app, headers={"Host": "127.0.0.1:7860"}) as client:
        yield client


class TestSubmitPageRenders:
    def test_configured_get_submit_returns_200(self, submit_client):
        resp = submit_client.get("/submit")
        assert resp.status_code == 200
        assert "Submit a Job" in resp.text

    def test_get_submit_english(self, submit_client):
        # ?lang= sets the language cookie via a 303 redirect (see
        # app/main.py language_switch); the next GET renders in that
        # language. Both hops must be 200, never a 500.
        first = submit_client.get("/submit?lang=en", follow_redirects=False)
        assert first.status_code == 303
        resp = submit_client.get("/submit")
        assert resp.status_code == 200
        assert "Submit a Job" in resp.text

    def test_get_submit_chinese(self, submit_client):
        first = submit_client.get("/submit?lang=zh", follow_redirects=False)
        assert first.status_code == 303
        resp = submit_client.get("/submit")
        assert resp.status_code == 200
        assert "提交作业" in resp.text

    def test_page_shows_sbatch_command_sketch(self, submit_client):
        resp = submit_client.get("/submit")
        assert resp.status_code == 200
        # The teaching sketch of the sbatch command must render.
        assert "sbatch --chdir=" in resp.text

    def test_partition_flag_is_html_escaped(self, submit_client, monkeypatch):
        # partition_flag comes from local config. HTML metacharacters in a
        # configured partition value must render escaped (visible as text),
        # never raw markup — the subtitle uses |safe for the trusted static
        # HTML, so the interpolated value itself has to be escaped.
        from app.config import DEFAULT_CONFIG, _build_settings

        config = dict(DEFAULT_CONFIG)
        config["slurm_partition"] = "GPU<&script>"
        config["allowed_partitions"] = ["GPU<&script>"]
        monkeypatch.setattr("app.routers.submit.get_settings", lambda: _build_settings(config))

        resp = submit_client.get("/submit")
        assert resp.status_code == 200
        assert "--partition=GPU&lt;&amp;script&gt;" in resp.text
        # The raw value must never appear unescaped anywhere in the page.
        assert "GPU<&script>" not in resp.text


class TestSubmitErrorFlow:
    def test_submit_error_redirect_renders_error_page(self, submit_client, monkeypatch):
        # Simulates "sbatch missing": submit_script raises, the handler
        # must 303-redirect to /submit?message=... and the error page
        # must render 200 with the visible message (Scenario B guard).
        def _sbatch_missing(**kwargs):
            raise SlurmSubmitError("sbatch: command not found (test)")

        monkeypatch.setattr("app.routers.submit.submit_script", _sbatch_missing)
        resp = submit_client.post(
            "/submit",
            data={
                "script_text": "#!/bin/bash\necho hi\n",
                "job_name": "ok",
                "partition": "",
                "gres": "",
                "cpus_per_task": 1,
                "mem": "4G",
                "time_limit": "00:05:00",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert location.startswith("/submit?message=")
        assert "message_type=error" in location

        error_page = submit_client.get(location)
        assert error_page.status_code == 200
        assert "sbatch: command not found" in error_page.text
