"""SLURM integration: submit / cancel / query with whitelist validation.

v2 model: jobs are submitted from the single user workspace.  Submission
is equivalent to `sbatch --chdir=<workspace> --partition=... <script>`.
All subprocesses use list arguments — never shell=True.
"""

import os
import pwd
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.config import get_settings
from app.job_store import create_job, get_known_job_ids
from app.models import JobRecord
from app.security import ensure_path_under_root

SETTINGS = get_settings()
ALLOWED_PARTITIONS = SETTINGS.allowed_partitions
ALLOWED_GRES = SETTINGS.allowed_gres
DEFAULT_PARTITION = SETTINGS.slurm_partition
DEFAULT_GRES = SETTINGS.default_gres
DEFAULT_CPUS_PER_TASK = SETTINGS.default_cpus
DEFAULT_MEM = SETTINGS.default_mem
DEFAULT_TIME_LIMIT = SETTINGS.default_time
SLURM_QUERY_TIMEOUT = 3

SCRIPT_SUFFIXES = {".sh", ".sbatch", ".py"}

# SLURM status codes -> short English labels (v2 UI is English-first)
SLURM_STATUS_LABELS: Dict[str, str] = {
    "RUNNING": "Running",
    "R": "Running",
    "PENDING": "Pending",
    "PD": "Pending",
    "CONFIGURING": "Configuring",
    "CF": "Configuring",
    "COMPLETED": "Completed",
    "CD": "Completed",
    "COMPLETING": "Completing",
    "CG": "Completing",
    "CANCELLED": "Cancelled",
    "CA": "Cancelled",
    "FAILED": "Failed",
    "F": "Failed",
    "TIMEOUT": "Timeout",
    "TO": "Timeout",
    "NODE_FAIL": "Node Failure",
    "NF": "Node Failure",
    "PREEMPTED": "Preempted",
    "PR": "Preempted",
    "BOOT_FAIL": "Boot Failure",
    "BF": "Boot Failure",
    "DEADLINE": "Deadline Exceeded",
    "DL": "Deadline Exceeded",
    "OUT_OF_MEMORY": "Out of Memory",
    "OOM": "Out of Memory",
    "SUSPENDED": "Suspended",
    "S": "Suspended",
    "REQUEUED": "Requeued",
    "RQ": "Requeued",
    "RESIZING": "Resizing",
    "RS": "Resizing",
    "STOPPED": "Stopped",
    "ST": "Stopped",
}

RUNNING_STATUS_CODES = {"RUNNING", "R", "COMPLETING", "CG", "CONFIGURING", "CF", "REQUEUED", "RQ", "RESIZING", "RS", "SUSPENDED", "S"}

TERMINAL_SLURM_CODES = {
    "COMPLETED", "CD", "CANCELLED", "CA", "FAILED", "F",
    "TIMEOUT", "TO", "NODE_FAIL", "NF", "PREEMPTED", "PR",
    "BOOT_FAIL", "BF", "DEADLINE", "DL", "OUT_OF_MEMORY", "OOM",
    "STOPPED", "ST",
}

JOB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
MEM_PATTERN = re.compile(r"^[0-9]+[GM]$")
TIME_PATTERN = re.compile(r"^(?:[0-9]+-)?[0-9]{1,2}:[0-9]{2}:[0-9]{2}$")
SCRIPT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+\.(?:sh|sbatch|py)$")


@dataclass(frozen=True)
class SlurmSubmitResult:
    job_id: str
    script_path: Path
    output_path: Path
    sbatch_stdout: str
    sbatch_stderr: str


@dataclass(frozen=True)
class SlurmCancelResult:
    ok: bool
    message: str
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class SlurmJobTiming:
    elapsed_time: str = "unknown"
    end_time: str = "unknown"


class SlurmSubmitError(RuntimeError):
    pass


def validate_slurm_job_id(job_id: str) -> str:
    if not job_id or not str(job_id).isdigit():
        raise ValueError("Job ID must be numeric")
    return str(job_id)


def validate_job_name(job_name: str) -> str:
    if not job_name or not JOB_NAME_PATTERN.fullmatch(job_name):
        raise ValueError("Job name may only contain A-Z, a-z, 0-9, _ and -")
    return job_name


def validate_partition(partition: str) -> str:
    """Validate a partition choice.

    Empty means "no --partition flag" (SLURM's native default); any
    non-empty value must be on the allowlist.
    """
    partition = (partition or "").strip()
    if partition and partition not in ALLOWED_PARTITIONS:
        raise ValueError("SLURM partition is not on the whitelist")
    return partition


def validate_gres(gres: str) -> str:
    """Validate a GRES choice.

    Empty means "no --gres flag" (SLURM's native default); any non-empty
    value must be on the allowlist.
    """
    gres = (gres or "").strip()
    if gres and gres not in ALLOWED_GRES:
        raise ValueError("GPU request is not on the whitelist")
    return gres


def validate_cpus_per_task(cpus_per_task: int) -> int:
    try:
        cpus = int(cpus_per_task)
    except (TypeError, ValueError):
        raise ValueError("CPU count must be an integer between 1 and 32")
    if cpus < 1 or cpus > 32:
        raise ValueError("CPU count must be an integer between 1 and 32")
    return cpus


def validate_mem(mem: str) -> str:
    if not mem or not MEM_PATTERN.fullmatch(mem):
        raise ValueError("Memory must match e.g. 16G or 64000M")
    amount = int(mem[:-1])
    if amount < 1:
        raise ValueError("Memory must be greater than 0")
    return mem


def validate_time_limit(time_limit: str) -> str:
    if not time_limit or not TIME_PATTERN.fullmatch(time_limit):
        raise ValueError("Time limit must match e.g. 00:30:00 or 1-00:00:00")
    clock = time_limit.split("-", 1)[-1]
    parts = [int(part) for part in clock.split(":")]
    if parts[1] >= 60 or parts[2] >= 60:
        raise ValueError("Time limit must match e.g. 00:30:00 or 1-00:00:00")
    return time_limit


def validate_script_filename(filename: str) -> str:
    if not filename:
        raise ValueError("Script file name is required")
    name = Path(filename).name
    if name != filename or "/" in filename or "\\" in filename:
        raise ValueError("Script file name must not contain directory components")
    if not SCRIPT_NAME_PATTERN.fullmatch(name):
        raise ValueError("Script file name must end in .sh, .sbatch or .py and use only letters, digits, _ - .")
    return name


def make_unique_script_path(scripts_dir: Path, script_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = scripts_dir / f"{Path(script_name).stem}_{timestamp}{Path(script_name).suffix}"
    counter = 1
    while candidate.exists():
        candidate = scripts_dir / f"{Path(script_name).stem}_{timestamp}_{counter}{Path(script_name).suffix}"
        counter += 1
    return candidate.resolve()


def normalize_script_content(content: str) -> str:
    """Ensure the script has a shebang (teaching-friendly default: bash)."""
    stripped = content.lstrip()
    if stripped.startswith("#!"):
        return content
    return "#!/usr/bin/env bash\n" + content


def build_python_wrapper(
    *,
    script_relpath: str,
    job_name: str,
    partition: str,
    gres: str,
    cpus_per_task: int,
    mem: str,
    time_limit: str,
    workspace: Path,
) -> str:
    """Generate an sbatch wrapper that runs a Python script.

    The wrapper is submitted from the workspace directory (sbatch --chdir)
    and invokes ``python3 <script>``.  Output still lands in
    ``slurm-<jobid>.out`` / ``.err`` via the CLI arguments passed by
    :func:`submit_script`.  All interpolated values are already whitelist
    validated by the caller.
    """
    quoted_workspace = shlex.quote(str(workspace))
    quoted_script = shlex.quote(script_relpath)
    lines = [
        "#!/usr/bin/env bash",
        f"#SBATCH --job-name={job_name}",
        # partition / GRES directives are only emitted when configured
        # (empty = SLURM's native default, matching submit_script).
    ]
    if partition:
        lines.append(f"#SBATCH --partition={partition}")
    if gres:
        lines.append(f"#SBATCH --gres={gres}")
    lines += [
        f"#SBATCH --cpus-per-task={cpus_per_task}",
        f"#SBATCH --mem={mem}",
        f"#SBATCH --time={time_limit}",
        "",
        "set -euo pipefail",
        "",
        f"cd {quoted_workspace}",
        "",
        'echo "========== Job Info =========="',
        'echo "Job ID: ${SLURM_JOB_ID}"',
        'echo "Job Name: ${SLURM_JOB_NAME}"',
        'echo "Node: ${SLURMD_NODENAME}"',
        'echo "Python: $(which python3)"',
        "python3 --version",
        'echo "=============================="',
        "",
        f'echo "========== Running: {script_relpath} =========="',
        f"python3 {quoted_script}",
    ]
    return "\n".join(lines) + "\n"


def submit_script(
    *,
    script_content: str,
    script_filename: str,
    job_name: str,
    partition: str,
    gres: str,
    cpus_per_task: int,
    mem: str,
    time_limit: str,
    workspace: Path,
    source: str = "paste",
) -> SlurmSubmitResult:
    """Write the script into the workspace and submit it via sbatch.

    Equivalent to: sbatch --chdir=<workspace> --partition=... run.sbatch
    Output goes to <workspace>/slurm-<jobid>.out.
    """
    if not script_content or not script_content.strip():
        raise SlurmSubmitError("Script content is empty")
    validated_job_name = validate_job_name(job_name)
    validated_partition = validate_partition(partition)
    validated_gres = validate_gres(gres)
    validated_cpus = validate_cpus_per_task(cpus_per_task)
    validated_mem = validate_mem(mem)
    validated_time_limit = validate_time_limit(time_limit)
    script_filename = validate_script_filename(script_filename)

    resolved_workspace = workspace.expanduser().resolve()
    ensure_path_under_root(resolved_workspace, resolved_workspace, "workspace path invalid")

    scripts_dir = resolved_workspace / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Python sources are wrapped in an automatically generated sbatch script.
    if script_filename.endswith(".py"):
        py_path = make_unique_script_path(scripts_dir, script_filename)
        ensure_path_under_root(py_path, scripts_dir, "script path invalid")
        py_path.write_text(script_content, encoding="utf-8")
        py_path.chmod(0o750)

        wrapper_path = make_unique_script_path(scripts_dir, f"run_{Path(script_filename).stem}.sbatch")
        ensure_path_under_root(wrapper_path, scripts_dir, "script path invalid")
        wrapper_content = build_python_wrapper(
            script_relpath=f"scripts/{py_path.name}",
            job_name=validated_job_name,
            partition=validated_partition,
            gres=validated_gres,
            cpus_per_task=validated_cpus,
            mem=validated_mem,
            time_limit=validated_time_limit,
            workspace=resolved_workspace,
        )
        wrapper_path.write_text(wrapper_content, encoding="utf-8")
        wrapper_path.chmod(0o750)
        submit_path = wrapper_path
        record_script_name = script_filename
    else:
        script_path = make_unique_script_path(scripts_dir, script_filename)
        ensure_path_under_root(script_path, scripts_dir, "script path invalid")
        script_path.write_text(normalize_script_content(script_content), encoding="utf-8")
        script_path.chmod(0o750)
        submit_path = script_path
        record_script_name = script_filename

    sbatch_args = [
        "sbatch",
        "--job-name", validated_job_name,
        "--cpus-per-task", str(validated_cpus),
        "--mem", validated_mem,
        "--time", validated_time_limit,
        "--output", "slurm-%j.out",
        "--error", "slurm-%j.err",
    ]
    # partition / GRES are only passed when configured; empty means
    # "let SLURM use its native default".
    if validated_partition:
        sbatch_args += ["--partition", validated_partition]
    if validated_gres:
        sbatch_args += ["--gres", validated_gres]
    sbatch_args.append(str(submit_path))

    try:
        result = subprocess.run(
            sbatch_args,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=str(resolved_workspace),
        )
    except FileNotFoundError:
        raise SlurmSubmitError("sbatch was not found on this system")
    except subprocess.TimeoutExpired:
        raise SlurmSubmitError("sbatch submission timed out")

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"return code {result.returncode}"
        raise SlurmSubmitError(detail)

    job_id = parse_job_id(result.stdout)
    output_path = (resolved_workspace / f"slurm-{job_id}.out").resolve()

    record = JobRecord(
        job_id=job_id,
        job_name=validated_job_name,
        script_name=record_script_name,
        source=source,
        submit_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        partition=validated_partition,
        gres=validated_gres,
        cpus_per_task=validated_cpus,
        mem=validated_mem,
        time_limit=validated_time_limit,
        status="SUBMITTED",
        workspace_path=str(resolved_workspace),
        output_path=str(output_path),
    )
    create_job(record)

    return SlurmSubmitResult(
        job_id=job_id,
        script_path=submit_path,
        output_path=output_path,
        sbatch_stdout=result.stdout.strip(),
        sbatch_stderr=result.stderr.strip(),
    )


def parse_job_id(stdout: str) -> str:
    match = re.search(r"Submitted batch job\s+([0-9]+)", stdout)
    if not match:
        raise SlurmSubmitError("Could not parse the Job ID from sbatch output")
    return match.group(1)


def translate_slurm_status(raw_status: str) -> str:
    if not raw_status:
        return "Unknown"
    key = raw_status.strip().upper()
    return SLURM_STATUS_LABELS.get(key, raw_status.strip())


def get_job_status_from_sacct(job_id: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["sacct", "-j", job_id, "--format", "State", "--noheader", "--parsable2"],
            capture_output=True,
            text=True,
            timeout=SLURM_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("."):
            return line
    first_line = result.stdout.splitlines()[0].strip()
    return first_line if first_line else None


def get_job_status(job_id: str) -> str:
    try:
        validated_job_id = validate_slurm_job_id(job_id)
    except ValueError:
        return "Unknown"

    try:
        result = subprocess.run(
            ["squeue", "-j", validated_job_id, "-h", "-o", "%T"],
            capture_output=True,
            text=True,
            timeout=SLURM_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        result = None

    if result is not None and result.returncode == 0:
        raw_status = result.stdout.strip()
        if raw_status:
            return translate_slurm_status(raw_status.splitlines()[0].strip())

    sacct_status = get_job_status_from_sacct(job_id)
    if sacct_status:
        return translate_slurm_status(sacct_status)

    if result is not None and result.returncode != 0 and result.stdout.strip():
        raw = result.stdout.strip().splitlines()[0].strip()
        if raw and raw.upper() in SLURM_STATUS_LABELS:
            return translate_slurm_status(raw)

    return "Unknown"


def get_active_jobs_status() -> Dict[str, str]:
    """One squeue call returning {job_id: label} for all active jobs."""
    try:
        result = subprocess.run(
            ["squeue", "-h", "-o", "%i|%T"],
            capture_output=True,
            text=True,
            timeout=SLURM_QUERY_TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {}

    if result.returncode != 0:
        return {}

    status_map: Dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) >= 2:
            job_id = parts[0].strip()
            raw_status = parts[1].strip()
            if job_id and raw_status:
                status_map[job_id] = translate_slurm_status(raw_status)
    return status_map


def normalize_slurm_time(value: str, default: str = "unknown") -> str:
    value = (value or "").strip()
    if not value or value in {"N/A", "Unknown", "UnknownTime", "None"}:
        return default
    return value.replace("T", " ")


def get_active_job_timing(job_id: str) -> SlurmJobTiming:
    result = subprocess.run(
        ["squeue", "-j", job_id, "-h", "-o", "%M|%e"],
        capture_output=True,
        text=True,
        timeout=SLURM_QUERY_TIMEOUT,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return SlurmJobTiming()

    line = result.stdout.strip().splitlines()[0]
    parts = line.split("|", 1)
    elapsed_time = normalize_slurm_time(parts[0] if parts else "", "unknown")
    end_time = normalize_slurm_time(parts[1] if len(parts) > 1 else "", "not finished")
    return SlurmJobTiming(elapsed_time=elapsed_time, end_time=end_time)


def get_accounted_job_timing(job_id: str) -> SlurmJobTiming:
    result = subprocess.run(
        ["scontrol", "show", "job", job_id],
        capture_output=True,
        text=True,
        timeout=SLURM_QUERY_TIMEOUT,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return SlurmJobTiming()

    elapsed_match = re.search(r"\bRunTime=([^\s]+)", result.stdout)
    end_match = re.search(r"\bEndTime=([^\s]+)", result.stdout)
    return SlurmJobTiming(
        elapsed_time=normalize_slurm_time(elapsed_match.group(1) if elapsed_match else "", "unknown"),
        end_time=normalize_slurm_time(end_match.group(1) if end_match else "", "unknown"),
    )


def get_job_timing(job_id: str) -> SlurmJobTiming:
    try:
        validated_job_id = validate_slurm_job_id(job_id)
    except ValueError:
        return SlurmJobTiming()

    for timing_lookup in [get_active_job_timing, get_accounted_job_timing]:
        try:
            timing = timing_lookup(validated_job_id)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if timing.elapsed_time != "unknown" or timing.end_time != "unknown":
            return timing
    return SlurmJobTiming()


def cancel_job(job_id: str) -> SlurmCancelResult:
    try:
        validated_job_id = validate_slurm_job_id(job_id)
    except ValueError as exc:
        return SlurmCancelResult(ok=False, message=str(exc))

    try:
        result = subprocess.run(
            ["scancel", validated_job_id],
            capture_output=True,
            text=True,
            timeout=SLURM_QUERY_TIMEOUT,
        )
    except FileNotFoundError:
        return SlurmCancelResult(ok=False, message="scancel was not found on this system")
    except subprocess.TimeoutExpired:
        return SlurmCancelResult(ok=False, message="Cancelling the job timed out")
    except OSError as exc:
        return SlurmCancelResult(ok=False, message=f"Cancelling failed: {str(exc)}")

    if result.returncode == 0:
        return SlurmCancelResult(
            ok=True,
            message="Job cancelled successfully",
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
        )

    detail = result.stderr.strip() or result.stdout.strip()
    message = "The job may already be finished"
    if detail:
        message = f"{message}: {detail}"
    return SlurmCancelResult(
        ok=False,
        message=message,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
    )


def discover_external_jobs() -> int:
    """Record jobs submitted outside the dashboard (squeue + sacct scan)."""
    current_user = os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name
    known_ids = get_known_job_ids()
    discovered = 0

    try:
        result = subprocess.run(
            ["squeue", "-u", current_user, "-h", "-o", "%i|%j|%T|%P|%b|%C|%m|%M"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        result = None

    if result is not None and result.returncode == 0:
        discovered += _discover_from_squeue_lines(result.stdout, known_ids)

    try:
        sacct_result = subprocess.run(
            ["sacct", "-u", current_user, "--starttime", "now-2days",
             "-o", "JobID,JobName,Partition,State,WorkDir,NCPUS,ReqMem",
             "--noheader", "--parsable2"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        sacct_result = None

    if sacct_result is not None and sacct_result.returncode == 0:
        discovered += _discover_from_sacct_lines(sacct_result.stdout, known_ids)

    return discovered


def _discover_from_squeue_lines(squeue_output: str, known_ids: set) -> int:
    discovered = 0
    for line in squeue_output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        job_id = parts[0].strip()
        if not job_id or not job_id.isdigit():
            continue
        if job_id in known_ids:
            continue

        job_name = parts[1].strip() or "unknown"
        raw_status = parts[2].strip()
        partition = parts[3].strip() or "unknown"
        tres_raw = parts[4].strip()
        cpus = parts[5].strip() or "1"
        mem = parts[6].strip() or "unknown"

        gres = "unknown"
        gres_match = re.search(r"gres/gpu[^=]*=(\S+)", tres_raw)
        if gres_match:
            gres = f"gpu:{gres_match.group(1)}"

        try:
            cpus_int = int(cpus)
        except (ValueError, TypeError):
            cpus_int = 1

        record = JobRecord(
            job_id=job_id,
            job_name=job_name,
            script_name="external",
            source="external",
            submit_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            partition=partition,
            gres=gres,
            cpus_per_task=cpus_int,
            mem=mem,
            time_limit="unknown",
            status=translate_slurm_status(raw_status),
        )
        create_job(record)
        discovered += 1
        known_ids.add(job_id)

    return discovered


def _discover_from_sacct_lines(sacct_output: str, known_ids: set) -> int:
    discovered = 0
    for line in sacct_output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        job_id = parts[0].strip()
        if not job_id or not job_id.isdigit():
            continue
        if job_id in known_ids:
            continue

        job_name = parts[1].strip() or "unknown"
        partition = parts[2].strip() or "unknown"
        raw_state = parts[3].strip()
        work_dir = parts[4].strip() if len(parts) > 4 else ""
        cpus = parts[5].strip() if len(parts) > 5 else "1"
        mem = parts[6].strip() if len(parts) > 6 else "unknown"

        if raw_state.upper() not in TERMINAL_SLURM_CODES:
            continue

        try:
            cpus_int = int(cpus)
        except (ValueError, TypeError):
            cpus_int = 1

        record = JobRecord(
            job_id=job_id,
            job_name=job_name,
            script_name="external",
            source="external",
            submit_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            partition=partition,
            gres="unknown",
            cpus_per_task=cpus_int,
            mem=mem,
            time_limit="unknown",
            status=translate_slurm_status(raw_state),
            workspace_path=work_dir if work_dir not in ("", "Unknown", "N/A") else "",
        )
        create_job(record)
        discovered += 1
        known_ids.add(job_id)

    return discovered
