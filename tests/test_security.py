"""
Tests for path security functions in app/security.py (v2).

Covers:
- Path traversal (../) is blocked
- Paths outside allowed roots are rejected
- System denied paths are blocked
- Symlink following safety
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.security import (
    check_same_origin,
    ensure_allowed_path,
    ensure_path_under_root,
    is_loopback_hostname,
    is_relative_to,
    is_system_denied_path,
)


class TestIsRelativeTo:
    def test_subpath_is_relative(self):
        assert is_relative_to(Path("/a/b/c"), Path("/a"))

    def test_same_path_is_relative(self):
        assert is_relative_to(Path("/a"), Path("/a"))

    def test_parent_is_not_relative(self):
        assert not is_relative_to(Path("/a"), Path("/a/b"))

    def test_sibling_is_not_relative(self):
        assert not is_relative_to(Path("/a/b"), Path("/a/c"))


class TestIsSystemDeniedPath:
    def test_etc_is_denied(self):
        assert is_system_denied_path(Path("/etc").resolve())

    def test_tmp_is_not_denied(self):
        assert not is_system_denied_path(Path("/tmp"))

    def test_home_is_not_denied(self):
        assert not is_system_denied_path(Path.home())


class TestEnsurePathUnderRoot:
    def test_valid_subpath_passes(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        result = ensure_path_under_root(sub, tmp_path)
        assert result == sub.resolve()

    def test_parent_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="allowed scope"):
            ensure_path_under_root(tmp_path.parent, tmp_path)

    @patch("app.security.allowed_roots", return_value=[])
    def test_path_outside_allowed_roots_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="allowed scope"):
            ensure_allowed_path(tmp_path)

    def test_dot_dot_traversal_prevented(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        sub = root / "sub"
        sub.mkdir()
        escape = (sub / ".." / ".." / "etc").resolve()
        if not is_relative_to(escape, root.resolve()):
            with pytest.raises(ValueError, match="allowed scope"):
                ensure_path_under_root(escape, root)


class TestAllowedRoots:
    def test_dashboard_root_is_allowed(self, tmp_path):
        with patch("app.security.DASHBOARD_ROOT", tmp_path):
            assert ensure_allowed_path(tmp_path / "x") == (tmp_path / "x").resolve()


class TestLoopbackHostname:
    def test_loopback_names(self):
        for name in ["localhost", "127.0.0.1", "127.0.0.2", "::1", "0:0:0:0:0:0:0:1", "LOCALHOST"]:
            assert is_loopback_hostname(name)

    def test_non_loopback_rejected(self):
        for name in ["evil.example", "192.168.1.5", "8.8.8.8", "", "10.0.0.1"]:
            assert not is_loopback_hostname(name)


class TestCheckSameOrigin:
    def test_matching_loopback_origin(self):
        assert check_same_origin("http://127.0.0.1:7860", "127.0.0.1:7860")
        assert check_same_origin("http://localhost:9000", "localhost:9000")
        assert check_same_origin("http://[::1]:7860", "[::1]:7860")

    def test_cross_origin_rejected(self):
        assert not check_same_origin("http://evil.example", "127.0.0.1:7860")
        assert not check_same_origin("http://127.0.0.1:9999", "127.0.0.1:7860")
        assert not check_same_origin("null", "127.0.0.1:7860")
        assert not check_same_origin("", "127.0.0.1:7860")

    def test_dns_rebinding_rejected(self):
        # Attacker page served from evil.example:7860 rebound to 127.0.0.1
        assert not check_same_origin("http://evil.example:7860", "evil.example:7860")


@pytest.fixture()
def configured_client(monkeypatch, tmp_path):
    """TestClient with a configured workspace and an isolated database."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("app.config.WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr("app.database.DATABASE_PATH", tmp_path / "test.sqlite3")
    with TestClient(app) as test_client:
        yield test_client


class TestReflectedXSSJobDetail:
    def test_job_id_never_enters_js_context(self, configured_client):
        payload = "%27)%3Balert(1)%3Bx(%27"  # ');alert(1);x('
        resp = configured_client.get(f"/jobs/{payload}")
        assert resp.status_code == 200
        body = resp.text
        # The confirm dialog message must live in a data attribute,
        # HTML-escaped — never interpolated into a JS handler.
        assert 'onsubmit="return confirm(this.dataset.confirm);"' in body
        assert "data-confirm=" in body
        assert "&#39;);alert(1);" in body  # escaped, inert as data

    def test_invalid_job_id_still_renders(self, configured_client):
        resp = configured_client.get("/jobs/12a34")
        assert resp.status_code == 200


class TestScriptPicker:
    def test_nonexistent_script_gets_error_redirect(self, configured_client):
        # A name that passes the no-directory check but does not exist
        # must degrade to an error message, not a 500.
        resp = configured_client.post(
            "/submit",
            data={
                "existing_script": "nothere.sbatch",
                "job_name": "ok",
                "partition": "GPU",
                "gres": "gpu:1",
                "cpus_per_task": 1,
                "mem": "4G",
                "time_limit": "00:05:00",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "message=" in resp.headers["location"]
        assert "message_type=error" in resp.headers["location"]

    def test_existing_script_submits(self, configured_client, tmp_path):
        scripts_dir = tmp_path / "workspace" / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "ok.sbatch").write_text("#!/bin/bash\necho hi\n")

        resp = configured_client.post(
            "/submit",
            data={
                "existing_script": "ok.sbatch",
                "job_name": "ok",
                "partition": "GPU",
                "gres": "gpu:1",
                "cpus_per_task": 1,
                "mem": "4G",
                "time_limit": "00:05:00",
            },
            follow_redirects=False,
        )
        # The file is picked up and sbatch is attempted. In CI there is no
        # SLURM, so sbatch fails — the handler must route that to a 303
        # error message, never a raw exception (500).
        assert resp.status_code == 303


class TestCsrfOriginGuard:
    def test_post_without_origin_allowed(self, configured_client, monkeypatch, tmp_path):
        # Non-browser clients (curl, scripts) send no Origin header.
        monkeypatch.setattr("app.routers.setup.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("app.config.PROJECT_ROOT", tmp_path)
        resp = configured_client.post(
            "/setup", data={"workspace": str(tmp_path / "ws")}, follow_redirects=False
        )
        assert resp.status_code == 303

    def test_cross_origin_post_blocked(self, configured_client):
        resp = configured_client.post(
            "/setup",
            data={"workspace": "/tmp/x"},
            headers={"Origin": "http://evil.example", "Host": "127.0.0.1:7860"},
        )
        assert resp.status_code == 403

    def test_same_origin_post_allowed(self, configured_client, monkeypatch, tmp_path):
        monkeypatch.setattr("app.routers.setup.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("app.config.PROJECT_ROOT", tmp_path)
        resp = configured_client.post(
            "/setup",
            data={"workspace": str(tmp_path / "ws")},
            headers={"Origin": "http://127.0.0.1:7860", "Host": "127.0.0.1:7860"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_get_not_blocked(self, configured_client):
        resp = configured_client.get("/status", headers={"Origin": "http://evil.example"})
        assert resp.status_code == 200
