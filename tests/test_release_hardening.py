"""Focused regression tests for the pre-release security hardening pass."""

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from app.config import DEFAULT_CONFIG, ConfigError, _build_settings
from app.main import MAX_REQUEST_BYTES, app
from app.routers.jobs import job_raw, resolve_output_path
from app.routers.status import validate_gpu_history_range


class TestBindHostConfiguration:
    def test_rejects_non_loopback_bind_hosts(self):
        for host in ["192.168.1.5", "10.0.0.1", "example.com", "0.0.0.0", "::", "*"]:
            config = dict(DEFAULT_CONFIG)
            config["server_bind_host"] = host
            with pytest.raises(ConfigError, match="loopback"):
                _build_settings(config)

    def test_accepts_loopback_aliases(self):
        for host in ["127.0.0.1", "127.0.0.2", "::1", "localhost"]:
            config = dict(DEFAULT_CONFIG)
            config["server_bind_host"] = host
            assert _build_settings(config).server_bind_host == host


class TestGpuHistoryRangeLimit:
    def test_small_day_window_is_allowed(self):
        validate_gpu_history_range("day", "2026-08-01", "2026-08-10")

    def test_large_day_window_is_rejected(self):
        with pytest.raises(ValueError, match="31-day limit"):
            validate_gpu_history_range("day", "2026-01-01", "2026-08-01")

    def test_reversed_window_is_rejected(self):
        with pytest.raises(ValueError, match="start must not be after end"):
            validate_gpu_history_range("month", "2026-08", "2026-01")

    def test_large_year_window_is_rejected(self):
        with pytest.raises(ValueError, match="3660-day limit"):
            validate_gpu_history_range("year", "2000", "2026")

    def test_invalid_week_format_is_rejected(self):
        with pytest.raises(ValueError):
            validate_gpu_history_range("week", "2026-W99", "2026-W30")


class TestJobOutputContainment:
    def test_recorded_output_outside_workspace_is_ignored(self, monkeypatch, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside.out"
        outside.write_text("secret\n")
        monkeypatch.setattr("app.config.WORKSPACE_ROOT", workspace)
        monkeypatch.setattr(
            "app.routers.jobs.get_job_by_job_id",
            lambda _job_id: {"output_path": str(outside)},
        )

        assert resolve_output_path("123") is None

    def test_raw_output_returns_file_response(self, monkeypatch, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        output = workspace / "slurm-123.out"
        output.write_text("hello\n")
        monkeypatch.setattr("app.config.WORKSPACE_ROOT", workspace)

        response = asyncio.run(job_raw("123"))
        assert isinstance(response, FileResponse)
        assert response.media_type == "text/plain"
        assert str(response.path) == str(output.resolve())

    def test_raw_output_rejects_non_numeric_job_id(self, monkeypatch, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setattr("app.config.WORKSPACE_ROOT", workspace)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(job_raw("../../etc/passwd"))
        assert exc_info.value.status_code == 400


class TestRequestSizeGuard:
    def test_oversized_form_request_is_rejected_before_route_parsing(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.database.DATABASE_PATH", tmp_path / "test.sqlite3")
        with TestClient(app, headers={"Host": "127.0.0.1:7860"}) as client:
            response = client.post(
                "/setup",
                content=b"x" * (MAX_REQUEST_BYTES + 1),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        assert response.status_code == 413
        assert response.headers["x-frame-options"] == "DENY"
