#!/usr/bin/env python3
"""GPU / CPU / memory usage monitor for slurm-dashboard.

Runs from crontab every 5 minutes (see README "GPU history collection"
for the cron entry):

Collects:
- per-GPU utilization, memory use, temperature, process list (with
  user/SLURM ownership, if available)
- CPU utilization (two /proc/stat samples) and load average
- system memory totals / available / usage (/proc/meminfo)
- appended to <repo>/data/gpu_history/gpu_history.jsonl
"""

import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
HISTORY_DIR = DASHBOARD_DIR / "data" / "gpu_history"
HISTORY_FILE = HISTORY_DIR / "gpu_history.jsonl"
SLURM_QUERY_TIMEOUT = 5


def run_command(cmd, timeout=SLURM_QUERY_TIMEOUT):
    """Run a read-only command safely and return its stdout lines."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip().splitlines() if result.returncode == 0 else []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def get_gpu_info():
    """Get per-GPU basics (index, name, utilization, memory, temperature)."""
    lines = run_command([
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,pci.bus_id",
        "--format=csv,noheader,nounits",
    ])
    gpus = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7:
            try:
                gpus.append({
                    "index": int(parts[0]),
                    "name": parts[1],
                    "utilization_gpu": float(parts[2]),
                    "utilization_memory": float(parts[3]),
                    "memory_used_mb": float(parts[4]),
                    "memory_total_mb": float(parts[5]),
                    "temperature_gpu": float(parts[6]) if parts[6] else None,
                    "bus_id": parts[7] if len(parts) > 7 else "",
                    "processes": [],
                })
            except (ValueError, IndexError):
                continue
    return gpus


def get_gpu_processes():
    """Get the process list per GPU (PID, process name, memory used)."""
    lines = run_command([
        "nvidia-smi",
        "--query-compute-apps=pid,process_name,used_memory,gpu_bus_id",
        "--format=csv,noheader,nounits",
    ])
    processes = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                processes.append({
                    "pid": int(parts[0]),
                    "process_name": parts[1],
                    "used_memory_mb": float(parts[2]),
                    "gpu_bus_id": parts[3] if len(parts) > 3 else "",
                })
            except (ValueError, IndexError):
                continue
    return processes


def get_pid_user(pid):
    """Look up the owner of a PID via ps."""
    lines = run_command(["ps", "-o", "user=", "-p", str(pid)])
    return lines[0].strip() if lines else None


def get_squeue_job_map():
    """Build a {user: {pid: {job_id, job_name}}} map.

    Lists active jobs via squeue, then resolves each job's PID via
    scontrol.
    """
    # list the active SLURM jobs
    job_lines = run_command([
        "squeue", "-h", "-o", "%i|%j|%u",
    ])
    if not job_lines:
        return {}

    pid_map = {}
    for line in job_lines:
        parts = line.strip().split("|")
        if len(parts) < 3:
            continue
        job_id, job_name, user = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not job_id:
            continue

        # resolve the job's PID via scontrol
        scontrol_lines = run_command([
            "scontrol", "show", "job", job_id, "-o",
        ])
        if not scontrol_lines:
            continue

        for sline in scontrol_lines:
            # extract PIDs from the OneLine output
            # format: ... Pid=12345 ...
            pid_match = re.search(r"\bPid=(\d+)", sline)
            if pid_match:
                pid = int(pid_match.group(1))
                if user not in pid_map:
                    pid_map[user] = {}
                pid_map[user][pid] = {
                    "job_id": job_id,
                    "job_name": job_name,
                }

    return pid_map


def build_process_user_map(processes):
    """Resolve the owner user and SLURM job for every GPU process.

    Strategy:
    1. Look up the username per PID with ps (fast)
    2. Build a squeue job -> PID map to attach job_id
    3. Walk the processes to build pid -> user
    """
    if not processes:
        return {}

    # step 1: batch-resolve users with ps
    pid_user = {}
    for proc in processes:
        pid = proc["pid"]
        user = get_pid_user(pid)
        if user:
            pid_user[pid] = user

    # step 2: squeue job -> PID map
    job_pid_map = get_squeue_job_map()

    # step 3: user -> PID -> job map
    user_pid_job = {}
    for user, pid_job_dict in job_pid_map.items():
        if user not in user_pid_job:
            user_pid_job[user] = {}
        user_pid_job[user].update(pid_job_dict)

    return {"pid_user": pid_user, "user_pid_job": user_pid_job}


def _read_cpu_stat():
    """Read the first line of /proc/stat, return (total, idle)."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().strip().split()
        values = [int(v) for v in parts[1:]]
        total = sum(values)
        idle = values[3] + values[4]  # idle + iowait
        return total, idle
    except (OSError, IndexError, ValueError):
        return 0, 0


def get_cpu_utilization():
    """Sample /proc/stat twice (0.1s apart) and return delta CPU %."""
    t1_total, t1_idle = _read_cpu_stat()
    time.sleep(0.1)
    t2_total, t2_idle = _read_cpu_stat()
    delta_total = t2_total - t1_total
    delta_idle = t2_idle - t1_idle
    if delta_total == 0:
        return 0.0
    return round((delta_total - delta_idle) / delta_total * 100, 1)


def get_loadavg():
    """Read /proc/loadavg, return the 1/5/15 minute load averages."""
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().strip().split()
        return {
            "load_1m": float(parts[0]),
            "load_5m": float(parts[1]),
            "load_15m": float(parts[2]),
        }
    except (OSError, IndexError, ValueError):
        return {"load_1m": None, "load_5m": None, "load_15m": None}


def get_memory_info():
    """Read /proc/meminfo, return total/available/used memory and %."""
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, value = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    mem[key] = int(value.strip().split()[0])  # kB
        total_mb = mem.get("MemTotal", 0) // 1024
        available_mb = mem.get("MemAvailable", 0) // 1024
        used_mb = total_mb - available_mb
        utilization_pct = round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0.0
        return {
            "total_mb": total_mb,
            "available_mb": available_mb,
            "used_mb": used_mb,
            "utilization_pct": utilization_pct,
        }
    except (OSError, ValueError):
        return {"total_mb": 0, "available_mb": 0, "used_mb": 0, "utilization_pct": 0.0}


def _normalize_bus_id(bus_id: str) -> str:
    """Lowercase/strip a PCI bus id for comparison."""
    return (bus_id or "").strip().lower()


def _bus_ids_match(a: str, b: str) -> bool:
    """True when two PCI bus ids refer to the same GPU.

    nvidia-smi can return the short form ("3D:00.0") or the full form
    ("00000000:3D:00.0") depending on driver version and query, so the
    two queries may disagree on the format. Compare exactly first, then
    by suffix containment.
    """
    a = _normalize_bus_id(a)
    b = _normalize_bus_id(b)
    if not a or not b:
        return False
    return a == b or a.endswith(b) or b.endswith(a)


def attach_processes_to_gpus(gpus, processes):
    """Attach enriched process dicts to their GPU by PCI bus id.

    Processes whose GPU cannot be determined are returned separately in
    ``unmatched`` and are never attributed to a GPU — there is no
    fallback to GPU 0, so a multi-GPU host never gets fabricated
    per-GPU data.
    """
    by_bus = {}
    for gpu in gpus:
        bus = _normalize_bus_id(gpu.get("bus_id", ""))
        if bus:
            by_bus[bus] = gpu

    unmatched = []
    for proc in processes:
        gpu_bus = _normalize_bus_id(proc.get("gpu_bus_id", ""))
        target = by_bus.get(gpu_bus)
        if target is None:
            for bus in by_bus:
                if _bus_ids_match(bus, gpu_bus):
                    target = by_bus[bus]
                    break
        if target is not None:
            target["processes"].append(proc)
        else:
            unmatched.append(proc)
    return gpus, unmatched


def collect():
    """Run one full collection, return a JSON-serializable dict."""
    now_local = datetime.now().astimezone()
    gpus = get_gpu_info()
    processes = get_gpu_processes()

    # resolve process ownership
    mapping = build_process_user_map(processes)
    pid_user = mapping.get("pid_user", {})
    user_pid_job = mapping.get("user_pid_job", {})

    # enrich each process with user / SLURM job ownership
    for proc in processes:
        pid = proc["pid"]
        user = pid_user.get(pid)

        # look up the SLURM job for this process
        job_id = None
        job_name = None
        if user and user in user_pid_job and pid in user_pid_job[user]:
            job_info = user_pid_job[user][pid]
            job_id = job_info.get("job_id")
            job_name = job_info.get("job_name")

        proc["user"] = user
        proc["job_id"] = job_id
        proc["job_name"] = job_name

    # attach processes to their GPU by PCI bus id; processes whose GPU
    # cannot be determined are recorded separately, never guessed.
    gpus, unmatched_processes = attach_processes_to_gpus(gpus, processes)

    return {
        "timestamp": now_local.isoformat(timespec="seconds"),
        "hostname": socket.gethostname(),
        "gpus": gpus,
        "unmatched_processes": unmatched_processes,
        "cpu": {
            "utilization_pct": get_cpu_utilization(),
            **get_loadavg(),
        },
        "memory": get_memory_info(),
    }


def main():
    """Collect once and append to the JSONL history file."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    try:
        data = collect()
    except Exception as exc:
        # write an error entry on failure for easier debugging
        error_entry = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "hostname": socket.gethostname(),
            "error": str(exc),
            "gpus": [],
            "cpu": {"utilization_pct": None, "load_1m": None, "load_5m": None, "load_15m": None},
            "memory": {"total_mb": 0, "available_mb": 0, "used_mb": 0, "utilization_pct": 0.0},
        }
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(error_entry, ensure_ascii=False) + "\n")
        raise

    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

    gpu_count = len(data["gpus"])
    process_count = sum(len(g["processes"]) for g in data["gpus"])
    print(f"[{data['timestamp']}] collected: {gpu_count} GPUs, {process_count} processes")


if __name__ == "__main__":
    main()
