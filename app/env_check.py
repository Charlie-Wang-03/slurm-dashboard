"""Environment self-check page data (read-only).

Checks whether the SLURM toolchain and GPU tooling are available,
plus a configuration summary for the running instance.
"""

import shutil
import subprocess
from typing import Dict, List

from app import config
from app.config import CURRENT_USER, DASHBOARD_DIR, HOSTNAME, get_settings

TOOLCHECK_COMMANDS: List[Dict] = [
    {"name": "sbatch", "command": ["sbatch", "--version"]},
    {"name": "squeue", "command": ["squeue", "--version"]},
    {"name": "sinfo", "command": ["sinfo", "--version"]},
    {"name": "sacct", "command": ["sacct", "--version"]},
    {"name": "scancel", "command": ["scancel", "--version"]},
    {"name": "scontrol", "command": ["scontrol", "--version"]},
    {"name": "nvidia-smi", "command": ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"]},
    {"name": "df", "command": ["df", "--version"]},
    {"name": "free", "command": ["free", "--version"]},
    {"name": "openssl", "command": ["openssl", "version"]},
]


def check_tool(tool: Dict) -> Dict:
    try:
        result = subprocess.run(
            tool["command"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        ok = result.returncode == 0
        output = (result.stdout or result.stderr).strip()
        return {
            "name": tool["name"],
            "command": " ".join(tool["command"]),
            "available": ok,
            "output": output or "no output",
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {
            "name": tool["name"],
            "command": " ".join(tool["command"]),
            "available": False,
            "output": "not available on this system",
        }


def get_tool_checks() -> List[Dict]:
    return [check_tool(tool) for tool in TOOLCHECK_COMMANDS]


def get_config_summary() -> Dict:
    settings = get_settings()
    return {
        "dashboard_dir": str(DASHBOARD_DIR),
        "workspace_root": str(config.WORKSPACE_ROOT) if config.WORKSPACE_ROOT else "(not configured)",
        "workspace_configured": config.WORKSPACE_ROOT is not None,
        "slurm_partition": settings.slurm_partition,
        "allowed_partitions": settings.allowed_partitions,
        "default_gres": settings.default_gres,
        "allowed_gres": settings.allowed_gres,
        "default_cpus": settings.default_cpus,
        "default_mem": settings.default_mem,
        "default_time": settings.default_time,
        "bind_host": settings.server_bind_host,
        "bind_port": settings.server_port,
        "ui_lang": settings.ui_lang,
        "current_user": CURRENT_USER,
        "hostname": HOSTNAME,
        "python_path": shutil.which("python3") or shutil.which("python") or "not found",
    }


def get_all_checks() -> Dict:
    return {
        "tool_checks": get_tool_checks(),
        "config_summary": get_config_summary(),
        "check_time": None,  # filled by the router
    }
