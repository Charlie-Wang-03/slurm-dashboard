"""
Security regression tests for the release trust boundaries.

Covers:
- Path traversal and symlink-root escapes
- Loopback Host / Origin enforcement
- Browser hardening headers and disabled API docs
- Reflected XSS regression
- Script picker / upload size limits
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.security import (
    check_loopback_host,
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

    def test_symlink_root_is_rejected(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        linked_root = tmp_path / "scripts"
        linked_root.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match="allowed scope"):
            ensure_path_under_root(linked_root / "job.sbatch", linked_root)


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


class TestLoopbackHostHeader:
    def test_loopback_host_headers(self):
        for value in ["127.0.0.1:7860", "127.0.0.2", "localhost:9000", "[::1]:7860"]:
            assert check_loopback_host(value)

    def test_non_loopback_or_malformed_rejected(self):
        for value in ["evil.example:7860", "192.168.1.5:7860", "10.0.0.1", "", "127.0.0.1:notaport", "user@127.0.0.1:7860"]:
            assert not check_loopback_host(value)


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

    def test_null_origin_with_same_origin_fetch_metadata_allowed(self):
        # Chrome 151 serializes loopback-page origins as literal "null" for
        # same-origin form POSTs. The browser's Sec-Fetch-Site attestation
        # (same-origin) plus a loopback Host is enough to accept.
        assert check_same_origin("null", "127.0.0.1:7860", sec_fetch_site="same-origin")
        assert check_same_origin("null", "localhost:7860", sec_fetch_site="same-origin")
        assert check_same_origin("null", "[::1]:7860", sec_fetch_site="same-origin")

    def test_null_origin_rejected_without_same_origin_fetch_metadata(self):
        assert not check_same_origin("null", "127.0.0.1:7860", sec_fetch_site="cross-site")
        assert not check_same_origin("null", "127.0.0.1:7860", sec_fetch_site="same-site")
        assert not check_same_origin("null", "127.0.0.1:7860", sec_fetch_site=None)
        assert not check_same_origin("null", "127.0.0.1:7860")

    def test_loopback_alias_spelling_is_not_normalized(self):
        # localhost and 127.0.0.1 are different origins; keep rejecting
        # the mismatch rather than silently broadening the trust scope.
        assert not check_same_origin("http://localhost:7860", "127.0.0.1:7860")
        assert not check_same_origin("http://127.0.0.1:7860", "localhost:7860")

    def test_non_loopback_host_rejected_even_with_matching_origin(self):
        assert not check_same_origin("http://127.0.0.1:7860", "evil.example:7860")


@pytest.fixture()
def configured_client(monkeypatch, tmp_path):
    """TestClient with a configured workspace and an isolated database."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("app.config.WORKSPACE_ROOT", tmp_path / "workspace")
    monkeypatch.setattr("app.database.DATABASE_PATH", tmp_path / "test.sqlite3")
    with TestClient(app, headers={"Host": "127.0.0.1:7860"}) as test_client:
        yield test_client


class TestHostAndBrowserGuards:
    def test_non_loopback_get_is_blocked(self, configured_client):
        resp = configured_client.get("/health", headers={"Host": "evil.example:7860"})
        assert resp.status_code == 403

    def test_loopback_get_is_allowed(self, configured_client):
        resp = configured_client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_security_headers_present(self, configured_client):
        resp = configured_client.get("/health")
        assert resp.headers["content-security-policy"] == "frame-ancestors 'none'"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["referrer-policy"] == "no-referrer"

    def test_fastapi_docs_surface_is_disabled(self, configured_client):
        assert configured_client.get("/docs").status_code == 404
        assert configured_client.get("/redoc").status_code == 404
        assert configured_client.get("/openapi.json").status_code == 404


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

    def test_symlinked_scripts_directory_is_not_listed(self, configured_client, tmp_path):
        from app.routers.submit import list_existing_scripts

        workspace = tmp_path / "workspace"
        outside = tmp_path / "outside"
        workspace.mkdir(parents=True, exist_ok=True)
        outside.mkdir()
        (outside / "secret.sbatch").write_text("echo hidden\n")
        (workspace / "scripts").symlink_to(outside, target_is_directory=True)
        assert list_existing_scripts() == []

    def test_oversized_upload_is_rejected(self, configured_client):
        from app.routers.submit import MAX_SCRIPT_BYTES

        resp = configured_client.post(
            "/submit",
            data={
                "job_name": "ok",
                "partition": "",
                "gres": "",
                "cpus_per_task": 1,
                "mem": "4G",
                "time_limit": "00:05:00",
            },
            files={"script_file": ("big.sbatch", b"x" * (MAX_SCRIPT_BYTES + 1), "text/plain")},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "too%20large" in resp.headers["location"] or "too+large" in resp.headers["location"]


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

    def test_cross_origin_get_is_readable_only_with_loopback_host(self, configured_client):
        # Origin is irrelevant for GET; the Host guard is the DNS-rebinding boundary.
        resp = configured_client.get("/health", headers={"Origin": "http://evil.example"})
        assert resp.status_code == 200
        rebound = configured_client.get(
            "/health",
            headers={"Origin": "http://evil.example", "Host": "evil.example:7860"},
        )
        assert rebound.status_code == 403

    def test_null_origin_same_origin_fetch_metadata_allowed(self, configured_client, monkeypatch, tmp_path):
        # Chrome 151 form POST regression: a literal "null" Origin on a
        # same-origin loopback navigation must not be treated as cross-site.
        monkeypatch.setattr("app.routers.setup.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("app.config.PROJECT_ROOT", tmp_path)
        resp = configured_client.post(
            "/setup",
            data={"workspace": str(tmp_path / "ws")},
            headers={
                "Origin": "null",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Host": "127.0.0.1:7860",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

    def test_null_origin_cross_site_fetch_metadata_blocked(self, configured_client):
        resp = configured_client.post(
            "/setup",
            data={"workspace": "/tmp/x"},
            headers={
                "Origin": "null",
                "Sec-Fetch-Site": "cross-site",
                "Host": "127.0.0.1:7860",
            },
        )
        assert resp.status_code == 403
