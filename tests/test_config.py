"""
Tests for configuration validation in app/config.py (v2).

Covers:
- Default settings are generated correctly
- 0.0.0.0 / :: / * bind host is rejected
- Mismatched partition/GRES whitelists are caught
- Workspace root resolution and system-root rejection
- config.local.json merging and error handling
"""

import json

import pytest

from app.config import (
    DEFAULT_CONFIG,
    ConfigError,
    _build_settings,
    _load_local_config,
    _require_mem,
    _require_name,
    _require_str,
    _require_str_list,
    _require_time,
)


# ── Validation of memory strings ──

def test_mem_valid_formats():
    assert _require_mem({"m": "16G"}, "m") == "16G"
    assert _require_mem({"m": "64000M"}, "m") == "64000M"
    assert _require_mem({"m": "1G"}, "m") == "1G"


def test_mem_rejects_invalid():
    with pytest.raises(ConfigError):
        _require_mem({"m": "16"}, "m")
    with pytest.raises(ConfigError):
        _require_mem({"m": "16GB"}, "m")
    with pytest.raises(ConfigError):
        _require_mem({"m": ""}, "m")
    with pytest.raises(ConfigError):
        _require_mem({"m": "g"}, "m")


# ── Validation of time strings ──

def test_time_valid_formats():
    assert _require_time({"t": "00:30:00"}, "t") == "00:30:00"
    assert _require_time({"t": "1-00:00:00"}, "t") == "1-00:00:00"


def test_time_rejects_invalid():
    with pytest.raises(ConfigError):
        _require_time({"t": "30:00"}, "t")
    with pytest.raises(ConfigError):
        _require_time({"t": "00:60:00"}, "t")
    with pytest.raises(ConfigError):
        _require_time({"t": "00:00:60"}, "t")
    with pytest.raises(ConfigError):
        _require_time({"t": ""}, "t")


# ── Validation of names ──

def test_name_valid_formats():
    assert _require_name({"n": "base"}, "n") == "base"
    assert _require_name({"n": "test_env-2.0"}, "n") == "test_env-2.0"


def test_name_rejects_invalid():
    with pytest.raises(ConfigError):
        _require_name({"n": "has space"}, "n")
    with pytest.raises(ConfigError):
        _require_name({"n": ""}, "n")
    with pytest.raises(ConfigError):
        _require_name({"n": "path/traversal"}, "n")


# ── Validation of string lists ──

def test_str_list_valid():
    assert _require_str_list({"a": ["GPU", "CPU"]}, "a") == ["GPU", "CPU"]


def test_str_list_rejects_empty():
    with pytest.raises(ConfigError):
        _require_str_list({"a": []}, "a")


def test_str_list_rejects_non_string():
    with pytest.raises(ConfigError):
        _require_str_list({"a": [1, 2]}, "a")


# ── Host binding safety ──

def test_rejects_unsafe_bind_host():
    """0.0.0.0, ::, and * must be rejected by config validation."""
    for unsafe in ["0.0.0.0", "::", "*"]:
        config = dict(DEFAULT_CONFIG)
        config["server_bind_host"] = unsafe
        with pytest.raises(ConfigError, match="server_bind_host"):
            _build_settings(config)


# ── Default settings ──

def test_default_bind_host_is_safe():
    assert DEFAULT_CONFIG["server_bind_host"] == "127.0.0.1"


def test_default_port():
    assert DEFAULT_CONFIG["server_port"] == 7860


def test_workspace_empty_by_default():
    """The first-run wizard is triggered when workspace_root is empty."""
    assert DEFAULT_CONFIG["workspace_root"] == ""


# ── Valid config builds successfully ──

def test_build_settings_with_valid_defaults(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULT_CONFIG)
    config["workspace_root"] = str(workspace)
    settings = _build_settings(config)
    assert settings.server_bind_host == "127.0.0.1"
    assert settings.server_port == 7860
    assert settings.workspace_root == workspace.resolve()
    assert settings.slurm_partition in settings.allowed_partitions
    assert settings.default_gres in settings.allowed_gres


def test_build_settings_empty_workspace_is_ok():
    """Empty workspace_root is a valid (unconfigured) state."""
    config = dict(DEFAULT_CONFIG)
    settings = _build_settings(config)
    assert settings.workspace_root is None


def test_build_settings_rejects_system_workspace(tmp_path):
    config = dict(DEFAULT_CONFIG)
    config["workspace_root"] = "/etc"
    with pytest.raises(ConfigError, match="workspace_root"):
        _build_settings(config)


def test_build_settings_partition_whitelist_mismatch():
    config = dict(DEFAULT_CONFIG)
    config["slurm_partition"] = "GPU"
    config["allowed_partitions"] = ["CPU"]
    with pytest.raises(ConfigError, match="slurm_partition"):
        _build_settings(config)


def test_build_settings_gres_whitelist_mismatch():
    config = dict(DEFAULT_CONFIG)
    config["default_gres"] = "gpu:1"
    config["allowed_gres"] = ["gpu:2"]
    with pytest.raises(ConfigError, match="default_gres"):
        _build_settings(config)


# ── Invalid config.json ──

def test_load_local_config_invalid_json(tmp_path):
    bad_config = tmp_path / "bad.json"
    bad_config.write_text("{invalid json")
    with pytest.raises(ConfigError, match="JSON error"):
        _load_local_config(bad_config)


def test_load_local_config_not_object(tmp_path):
    bad_config = tmp_path / "list.json"
    bad_config.write_text('["a", "b"]')
    with pytest.raises(ConfigError, match="JSON object"):
        _load_local_config(bad_config)


def test_load_local_config_unknown_keys(tmp_path):
    bad_config = tmp_path / "unknown.json"
    bad_config.write_text('{"unknown_key": 1}')
    with pytest.raises(ConfigError, match="unknown keys"):
        _load_local_config(bad_config)


def test_load_local_config_legacy_keys_rejected(tmp_path):
    """Legacy v1 keys (projects_root etc.) must be rejected loudly."""
    bad_config = tmp_path / "legacy.json"
    bad_config.write_text(json.dumps({"projects_root": "~/projects"}))
    with pytest.raises(ConfigError, match="unknown keys"):
        _load_local_config(bad_config)
