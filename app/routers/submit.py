from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.config import get_settings
from app.i18n import detect_language, get_strings
from app.security import ensure_path_under_root
from app.slurm import (
    DEFAULT_CPUS_PER_TASK,
    DEFAULT_GRES,
    DEFAULT_MEM,
    DEFAULT_PARTITION,
    DEFAULT_TIME_LIMIT,
    SlurmSubmitError,
    submit_script,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def list_existing_scripts() -> list:
    """List runnable files under workspace/scripts/ (sh, sbatch, py)."""
    if config.WORKSPACE_ROOT is None:
        return []
    scripts_dir = config.WORKSPACE_ROOT.expanduser().resolve() / "scripts"
    if not scripts_dir.is_dir():
        return []
    return sorted(
        p.name for p in scripts_dir.iterdir()
        if p.is_file() and p.suffix in {".sh", ".sbatch", ".py"}
    )


@router.get("/submit", response_class=HTMLResponse)
async def submit_form(request: Request, message: str = "", message_type: str = "info"):
    settings = get_settings()
    lang = detect_language(request, settings.ui_lang)
    strings = get_strings(lang)
    return templates.TemplateResponse(
        request,
        "submit.html",
        {
            "request": request,
            "lang": lang,
            "strings": strings,
            "page_title": strings["submit.title"],
            "active_page": "submit",
            "workspace": str(config.WORKSPACE_ROOT) if config.WORKSPACE_ROOT else "",
            "workspace_configured": config.WORKSPACE_ROOT is not None,
            "existing_scripts": list_existing_scripts(),
            "slurm_partition": settings.slurm_partition,
            "allowed_partitions": settings.allowed_partitions,
            "default_gres": settings.default_gres,
            "allowed_gres": settings.allowed_gres,
            "default_cpus": settings.default_cpus,
            "default_mem": settings.default_mem,
            "default_time": settings.default_time,
            "message": message,
            "message_type": message_type,
        },
    )


@router.post("/submit")
async def submit_job(
    request: Request,
    script_text: str = Form(""),
    script_filename: str = Form("run.sbatch"),
    job_name: str = Form(...),
    partition: str = Form(...),
    gres: str = Form(...),
    cpus_per_task: int = Form(...),
    mem: str = Form(...),
    time_limit: str = Form(...),
    script_file: UploadFile | None = File(None),
    existing_script: str = Form(""),
):
    try:
        if config.WORKSPACE_ROOT is None:
            raise SlurmSubmitError("Workspace is not configured yet — open Settings to set it up.")
        content = script_text
        source = "paste"
        filename = script_filename
        if existing_script:
            # Picked from the workspace scripts directory.
            scripts_dir = config.WORKSPACE_ROOT.expanduser().resolve() / "scripts"
            chosen = Path(existing_script).name
            if chosen != existing_script or "/" in existing_script or "\\" in existing_script:
                raise SlurmSubmitError("Script file name must not contain directory components")
            script_path = (scripts_dir / chosen).resolve()
            ensure_path_under_root(script_path, scripts_dir, "script path invalid")
            if not script_path.is_file():
                raise SlurmSubmitError("Script file not found in workspace scripts directory")
            content = script_path.read_text(encoding="utf-8")
            source = "existing"
            filename = chosen
        elif script_file is not None and script_file.filename:
            content = (await script_file.read()).decode("utf-8", errors="replace")
            source = "upload"
            filename = script_file.filename
        result = submit_script(
            script_content=content,
            script_filename=filename,
            job_name=job_name,
            partition=partition,
            gres=gres,
            cpus_per_task=cpus_per_task,
            mem=mem,
            time_limit=time_limit,
            workspace=config.WORKSPACE_ROOT,
            source=source,
        )
        return RedirectResponse(url=f"/jobs/{result.job_id}", status_code=303)
    except (SlurmSubmitError, ValueError) as exc:
        return RedirectResponse(
            url=f"/submit?message={quote(str(exc))}&message_type=error",
            status_code=303,
        )
