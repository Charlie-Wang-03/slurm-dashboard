"""Read-only cluster status collection.

Whitelisted commands only: sinfo / squeue / sacct / df / free / nvidia-smi.
All subprocesses use list arguments — never shell=True.
"""

import datetime
import subprocess
from typing import Dict, List

from app import config
from app.config import CURRENT_USER, DASHBOARD_DIR, HOSTNAME, HOME_DIR, get_settings

STATUS_COMMANDS = {
    "sinfo": ["sinfo"],
    "squeue": ["squeue", "-u", CURRENT_USER],
    "sacct": ["sacct", "-u", CURRENT_USER, "--starttime", "now-1days", "--format=JobID,JobName,State,Elapsed", "--noheader"],
    "df": ["df", "-h"],
    "free": ["free", "-h"],
    "nvidia-smi": ["nvidia-smi"],
}


def run_command(title: str, command: List[str], timeout: int = 10) -> Dict:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return with_display_state({
            "title": title,
            "command": " ".join(command),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "ok": result.returncode == 0,
            "error_message": None,
        })
    except subprocess.TimeoutExpired:
        return with_display_state({
            "title": title,
            "command": " ".join(command),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "ok": False,
            "error_message": "timeout",
        })
    except FileNotFoundError:
        return with_display_state({
            "title": title,
            "command": " ".join(command),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "ok": False,
            "error_message": "command not available on this system",
        })
    except Exception as exc:  # noqa: BLE001
        return with_display_state({
            "title": title,
            "command": " ".join(command),
            "stdout": "",
            "stderr": "",
            "returncode": -1,
            "ok": False,
            "error_message": str(exc),
        })


def with_display_state(result: Dict) -> Dict:
    has_output = bool(result.get("stdout") or result.get("stderr"))
    if result.get("ok") and has_output:
        result["status_label"] = "OK"
        result["status_badge_class"] = "badge-success"
    elif result.get("ok"):
        result["status_label"] = "No output"
        result["status_badge_class"] = "badge-muted"
    elif result.get("error_message") == "timeout":
        result["status_label"] = "Timeout"
        result["status_badge_class"] = "badge-warning"
    else:
        result["status_label"] = "Failed"
        result["status_badge_class"] = "badge-danger"
    result["has_output"] = has_output
    return result


def get_basic_info() -> Dict:
    settings = get_settings()
    return {
        "current_user": CURRENT_USER,
        "hostname": HOSTNAME,
        "current_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dashboard_dir": str(DASHBOARD_DIR),
        "workspace_dir": str(config.WORKSPACE_ROOT) if config.WORKSPACE_ROOT else "",
        "slurm_partition": settings.slurm_partition,
        "bind_host": settings.server_bind_host,
        "bind_port": settings.server_port,
    }


def get_slurm_status() -> List[Dict]:
    return [
        run_command("Partitions (sinfo)", ["sinfo"]),
        run_command("Node resource table (sinfo)", ["sinfo", "-o", "%P %N %t %c %m %G"]),
    ]


def get_user_jobs() -> List[Dict]:
    """Both views: the current user's queue and the full cluster queue."""
    return [
        run_command("My jobs (squeue)", ["squeue", "-u", CURRENT_USER]),
        run_command("All jobs (squeue)", ["squeue"]),
    ]


def get_gpu_status() -> List[Dict]:
    return [
        run_command("GPU status (nvidia-smi)", ["nvidia-smi"]),
    ]


def get_disk_status() -> List[Dict]:
    settings = get_settings()
    disk_paths = []
    candidates = [HOME_DIR, DASHBOARD_DIR]
    if config.WORKSPACE_ROOT is not None:
        candidates.append(config.WORKSPACE_ROOT)
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.exists() and str(resolved) not in disk_paths:
            disk_paths.append(str(resolved))
    return [
        run_command("Disk space (df)", ["df", "-h", *disk_paths]),
    ]


def get_memory_status() -> List[Dict]:
    return [
        run_command("Memory (free)", ["free", "-h"]),
    ]


def get_all_status() -> Dict:
    slurm_status = get_slurm_status()
    user_jobs = get_user_jobs()
    gpu_status = get_gpu_status()
    disk_status = get_disk_status()
    memory_status = get_memory_status()
    return {
        "basic_info": get_basic_info(),
        "slurm_status": slurm_status,
        "user_jobs": user_jobs,
        "gpu_status": gpu_status,
        "disk_status": disk_status,
        "memory_status": memory_status,
        "status_groups": [
            {
                "title": "SLURM",
                "description": "Partitions, node resources and your queue.",
                "items": [*slurm_status, *user_jobs],
            },
            {
                "title": "GPU",
                "description": "Shown when nvidia-smi is available.",
                "items": gpu_status,
            },
            {
                "title": "System resources",
                "description": "Read-only disk and memory status.",
                "items": [*disk_status, *memory_status],
            },
        ],
        "last_refresh": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
