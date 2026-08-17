"""Application configuration for slurm-dashboard.

v2 configuration model: a single user workspace (workspace_root) plus
SLURM whitelist defaults.  Everything else (projects/envs/data roots,
kernel/env defaults) has been removed.
"""

import getpass
import json
import re
import socket
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

HOME_DIR = Path.home().resolve()
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG: Dict[str, Any] = {
    # Empty string means "not configured yet" — the first-run wizard
    # writes a value here (default: ~/slurm-dashboard/workspace).
    "workspace_root": "",
    "slurm_partition": "GPU",
    "allowed_partitions": ["GPU"],
    "default_gres": "gpu:1",
    "allowed_gres": ["gpu:1"],
    "default_cpus": 4,
    "default_mem": "16G",
    "default_time": "00:30:00",
    "server_bind_host": "127.0.0.1",
    "server_port": 7860,
    "ui_lang": "auto",  # auto | en | zh
}

DANGEROUS_ROOTS = [
    Path("/"),
    Path("/etc"),
    Path("/root"),
    Path("/usr"),
    Path("/var"),
    Path("/bin"),
    Path("/sbin"),
    Path("/lib"),
    Path("/lib64"),
    Path("/boot"),
    Path("/dev"),
    Path("/proc"),
    Path("/sys"),
    Path("/run"),
]
MEM_PATTERN = re.compile(r"^[0-9]+[GM]$")
TIME_PATTERN = re.compile(r"^(?:[0-9]+-)?[0-9]{1,2}:[0-9]{2}:[0-9]{2}$")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Settings:
    workspace_root: Optional[Path]
    slurm_partition: str
    allowed_partitions: List[str]
    default_gres: str
    allowed_gres: List[str]
    default_cpus: int
    default_mem: str
    default_time: str
    server_bind_host: str
    server_port: int
    ui_lang: str


class ConfigError(RuntimeError):
    pass


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_dangerous_root(path: Path, field_name: str) -> None:
    for dangerous in DANGEROUS_ROOTS:
        if path == dangerous or (dangerous != Path("/") and _is_relative_to(path, dangerous)):
            raise ConfigError(f"{field_name} must not be a system directory: {path}")


def _require_str(config: Dict[str, Any], field_name: str) -> str:
    value = config[field_name]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_mem(config: Dict[str, Any], field_name: str) -> str:
    value = _require_str(config, field_name)
    if not MEM_PATTERN.fullmatch(value):
        raise ConfigError(f"{field_name} must match e.g. 16G or 64000M")
    return value


def _require_time(config: Dict[str, Any], field_name: str) -> str:
    value = _require_str(config, field_name)
    if not TIME_PATTERN.fullmatch(value):
        raise ConfigError(f"{field_name} must match e.g. 00:30:00 or 1-00:00:00")
    clock = value.split("-", 1)[-1]
    parts = [int(part) for part in clock.split(":")]
    if parts[1] >= 60 or parts[2] >= 60:
        raise ConfigError(f"{field_name} must match e.g. 00:30:00 or 1-00:00:00")
    return value


def _require_name(config: Dict[str, Any], field_name: str) -> str:
    value = _require_str(config, field_name)
    if not NAME_PATTERN.fullmatch(value):
        raise ConfigError(f"{field_name} may only contain A-Z, a-z, 0-9, _, -, .")
    return value


def _require_str_list(config: Dict[str, Any], field_name: str) -> List[str]:
    value = config[field_name]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{field_name} must be a non-empty string list")
    normalized = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{field_name}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    return normalized


def _require_int(config: Dict[str, Any], field_name: str, minimum: int, maximum: int | None = None) -> int:
    value = config[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field_name} must be an integer")
    if value < minimum:
        raise ConfigError(f"{field_name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{field_name} must be <= {maximum}")
    return value


def _load_local_config(config_path: Path) -> Dict[str, Any]:
    try:
        with config_path.open("r", encoding="utf-8") as file_obj:
            payload = json.load(file_obj)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{config_path} JSON error at line {exc.lineno}: {exc.msg}") from exc
    except OSError as exc:
        raise ConfigError(f"{config_path} could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{config_path} top level must be a JSON object")
    unknown_keys = sorted(set(payload) - set(DEFAULT_CONFIG))
    if unknown_keys:
        raise ConfigError(f"{config_path} contains unknown keys: {', '.join(unknown_keys)}")
    return payload


def _build_settings(config: Dict[str, Any]) -> Settings:
    workspace_value = config["workspace_root"]
    workspace_root: Optional[Path] = None
    if isinstance(workspace_value, str) and workspace_value.strip():
        workspace_root = Path(workspace_value).expanduser().resolve()
        if not workspace_root.exists():
            workspace_root.mkdir(parents=True, exist_ok=True)
        _reject_dangerous_root(workspace_root, "workspace_root")

    server_bind_host = _require_str(config, "server_bind_host")
    if server_bind_host in {"0.0.0.0", "::", "*"}:
        raise ConfigError("server_bind_host must be 127.0.0.1 (0.0.0.0 / :: / * rejected); access via SSH port forwarding")

    slurm_partition = _require_str(config, "slurm_partition")
    allowed_partitions = _require_str_list(config, "allowed_partitions")
    if slurm_partition not in allowed_partitions:
        raise ConfigError("slurm_partition must be in allowed_partitions")

    default_gres = _require_str(config, "default_gres")
    allowed_gres = _require_str_list(config, "allowed_gres")
    if default_gres not in allowed_gres:
        raise ConfigError("default_gres must be in allowed_gres")

    return Settings(
        workspace_root=workspace_root,
        slurm_partition=slurm_partition,
        allowed_partitions=allowed_partitions,
        default_gres=default_gres,
        allowed_gres=allowed_gres,
        default_cpus=_require_int(config, "default_cpus", minimum=1, maximum=32),
        default_mem=_require_mem(config, "default_mem"),
        default_time=_require_time(config, "default_time"),
        server_bind_host=server_bind_host,
        server_port=_require_int(config, "server_port", minimum=1, maximum=65535),
        ui_lang=config.get("ui_lang", "auto"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    config = dict(DEFAULT_CONFIG)
    config_path = PROJECT_ROOT / "config.local.json"
    if config_path.exists():
        config.update(_load_local_config(config_path))
    return _build_settings(config)


def reload_settings() -> Settings:
    """Re-read config.local.json and refresh the module-level settings.

    Called by the first-run wizard after writing the workspace path.
    Routers access settings through `app.config` module attributes, so the
    new value takes effect immediately without a restart.
    """
    get_settings.cache_clear()
    settings = get_settings()
    globals().update(
        {
            "SETTINGS": settings,
            "WORKSPACE_ROOT": settings.workspace_root,
            "DEFAULT_SLURM_PARTITION": settings.slurm_partition,
            "ALLOWED_SLURM_PARTITIONS": settings.allowed_partitions,
            "DEFAULT_GPU_GRES": settings.default_gres,
            "ALLOWED_GPU_GRES": settings.allowed_gres,
            "DEFAULT_CPUS_PER_TASK": settings.default_cpus,
            "DEFAULT_MEM": settings.default_mem,
            "DEFAULT_TIME_LIMIT": settings.default_time,
            "SERVER_BIND_HOST": settings.server_bind_host,
            "SERVER_PORT": settings.server_port,
            "UI_LANG": settings.ui_lang,
        }
    )
    return settings


SETTINGS = get_settings()

DASHBOARD_DIR = PROJECT_ROOT.resolve()
WORKSPACE_ROOT = SETTINGS.workspace_root
DEFAULT_SLURM_PARTITION = SETTINGS.slurm_partition
ALLOWED_SLURM_PARTITIONS = SETTINGS.allowed_partitions
DEFAULT_GPU_GRES = SETTINGS.default_gres
ALLOWED_GPU_GRES = SETTINGS.allowed_gres
DEFAULT_CPUS_PER_TASK = SETTINGS.default_cpus
DEFAULT_MEM = SETTINGS.default_mem
DEFAULT_TIME_LIMIT = SETTINGS.default_time
SERVER_BIND_HOST = SETTINGS.server_bind_host
SERVER_PORT = SETTINGS.server_port
UI_LANG = SETTINGS.ui_lang

CURRENT_USER = getpass.getuser()
HOSTNAME = socket.gethostname()
