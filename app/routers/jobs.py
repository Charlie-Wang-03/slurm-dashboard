from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.cluster_status import run_command
from app import config
from app.config import get_settings
from app.i18n import detect_language, get_strings
from app.job_store import get_job_by_job_id, list_jobs
from app.security import ensure_path_under_root
from app.slurm import (
    SlurmJobTiming,
    cancel_job,
    get_active_jobs_status,
    get_job_timing,
    validate_slurm_job_id,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

TAIL_LINES = 100


def tail_file(path: Path, max_lines: int = TAIL_LINES) -> str:
    """Return the last max_lines of a text file (best-effort)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file_obj:
            # Cheap tail for small files; stream backwards for large ones.
            size = path.stat().st_size
            if size < 512 * 1024:
                return "\n".join(file_obj.read().splitlines()[-max_lines:])
            file_obj.seek(max(0, size - 1024 * 1024))
            return "\n".join(file_obj.read().splitlines()[-max_lines:])
    except OSError:
        return ""


def resolve_output_path(job_id: str) -> Path | None:
    """slurm-<id>.out lives in the workspace (or the recorded path)."""
    record = get_job_by_job_id(job_id)
    candidates = []
    if record and record.get("output_path"):
        candidates.append(Path(record["output_path"]))
    if config.WORKSPACE_ROOT is not None:
        candidates.append(config.WORKSPACE_ROOT / f"slurm-{job_id}.out")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


@router.get("/jobs", response_class=HTMLResponse)
async def jobs_list(request: Request):
    active_status = get_active_jobs_status()
    active_jobs = [
        {"job_id": job_id, "status": label}
        for job_id, label in sorted(active_status.items())
    ]
    records = list_jobs(limit=200)
    lang = detect_language(request, get_settings().ui_lang)
    strings = get_strings(lang)
    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "request": request,
            "lang": lang,
            "strings": strings,
            "page_title": strings["jobs.title"],
            "active_page": "jobs",
            "active_jobs": active_jobs,
            "records": records,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    record = get_job_by_job_id(job_id)
    # SLURM job IDs are numeric. For anything else, skip the subprocess
    # lookups and render the page with empty state blocks (the cancel
    # and download endpoints validate the same way).
    try:
        validate_slurm_job_id(job_id)
    except ValueError:
        sacct = {
            "stdout": "",
            "stderr": "",
            "status_label": "Skipped",
            "status_badge_class": "badge-muted",
            "ok": False,
        }
        timing = SlurmJobTiming()
        output_path = None
    else:
        sacct = run_command(
            "Accounting (sacct)",
            [
                "sacct", "-j", job_id,
                "--format=JobID,JobName,Partition,State,Elapsed,End,ExitCode",
                "--noheader", "--parsable2",
            ],
        )
        timing = get_job_timing(job_id)
        output_path = resolve_output_path(job_id)
    tail_out = tail_file(output_path) if output_path else ""
    lang = detect_language(request, get_settings().ui_lang)
    strings = get_strings(lang)
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "request": request,
            "lang": lang,
            "strings": strings,
            "page_title": strings["job.title"].format(job_id=job_id),
            "active_page": "jobs",
            "job_id": job_id,
            "record": record,
            "sacct": sacct,
            "timing": timing,
            "tail_out": tail_out,
            "has_output": output_path is not None,
            "download_url": f"/jobs/{job_id}/download" if output_path else None,
        },
    )


@router.post("/jobs/{job_id}/cancel")
async def job_cancel(job_id: str):
    result = cancel_job(job_id)
    message = quote(result.message)
    return RedirectResponse(
        url=f"/jobs/{job_id}?message={message}&message_type={'success' if result.ok else 'error'}",
        status_code=303,
    )


@router.get("/jobs/{job_id}/download")
async def job_download(job_id: str):
    if config.WORKSPACE_ROOT is None:
        raise HTTPException(status_code=404, detail="no workspace configured")
    path = ensure_path_under_root(config.WORKSPACE_ROOT / f"slurm-{job_id}.out", config.WORKSPACE_ROOT)
    if not path.exists():
        raise HTTPException(status_code=404, detail="output file not found")
    return FileResponse(path, filename=path.name)


@router.get("/jobs/{job_id}/raw")
async def job_raw(job_id: str):
    """Plain-text view of the job output (for tailing in a terminal)."""
    if config.WORKSPACE_ROOT is None:
        raise HTTPException(status_code=404, detail="no workspace configured")
    path = ensure_path_under_root(config.WORKSPACE_ROOT / f"slurm-{job_id}.out", config.WORKSPACE_ROOT)
    if not path.exists():
        raise HTTPException(status_code=404, detail="output file not found")
    return PlainTextResponse(path.read_text(errors="replace"))
