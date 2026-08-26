"""First-run setup wizard tests: path resolution + first-run guard."""

from pathlib import Path

import pytest

from app.routers.setup import resolve_workspace_path


class TestResolveWorkspacePath:
    def test_expands_tilde_and_creates(self, tmp_path):
        raw = str(tmp_path / "my workspace")
        path = resolve_workspace_path(raw)
        assert path == (tmp_path / "my workspace").resolve()
        assert path.exists()

    def test_accepts_existing_dir(self, tmp_path):
        existing = tmp_path / "exist"
        existing.mkdir()
        assert resolve_workspace_path(str(existing)) == existing.resolve()

    def test_rejects_system_root(self):
        with pytest.raises(Exception):
            resolve_workspace_path("/etc")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            resolve_workspace_path("   ")


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, headers={"Host": "127.0.0.1:7860"}) as test_client:
        yield test_client


class TestFirstRunGuard:
    def test_redirects_when_no_workspace(self, client, monkeypatch):
        monkeypatch.setattr("app.config.WORKSPACE_ROOT", None)
        resp = client.get("/status", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/setup"

    def test_setup_and_health_reachable_without_workspace(self, client, monkeypatch):
        monkeypatch.setattr("app.config.WORKSPACE_ROOT", None)
        assert client.get("/setup").status_code == 200
        assert client.get("/health").status_code == 200

    def test_allowed_when_workspace_set(self, client, monkeypatch):
        monkeypatch.setattr("app.config.WORKSPACE_ROOT", Path(tmp_root()))
        resp = client.get("/status", follow_redirects=False)
        assert resp.status_code == 200


def tmp_root() -> str:
    import tempfile

    return tempfile.mkdtemp()
