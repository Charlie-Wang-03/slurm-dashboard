"""First-run setup wizard.

The workspace path is the one local setting a beginner must choose.
Visitors are redirected here automatically until a workspace is
configured (see app/main.py first_run_guard).  Saving writes
config.local.json and hot-reloads the settings — no restart needed.
"""

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import config
from app.config import PROJECT_ROOT, ConfigError, _reject_dangerous_root
from app.i18n import detect_language, get_strings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Default workspace = <repo>/workspace, derived from the actual project
# location so the wizard works no matter where the repo was cloned.
# (gitignored, like data/ and logs/.)
DEFAULT_WORKSPACE = PROJECT_ROOT / "workspace"


def resolve_workspace_path(raw: str) -> Path:
    """Expand ~, resolve, reject system directories, create if missing."""
    value = raw.strip()
    if not value:
        raise ValueError("workspace path must not be empty")
    path = Path(value).expanduser().resolve()
    _reject_dangerous_root(path, "workspace_root")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _save_workspace(path: Path) -> None:
    """Update workspace_root in config.local.json, preserving other keys."""
    config_path = PROJECT_ROOT / "config.local.json"
    payload = {}
    if config_path.exists():
        payload = config._load_local_config(config_path)
    payload["workspace_root"] = str(path)
    tmp = config_path.with_name(config_path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(config_path)


@router.get("/setup", response_class=HTMLResponse)
async def setup_form(request: Request, message: str = "", message_type: str = "info"):
    lang = detect_language(request, config.get_settings().ui_lang)
    strings = get_strings(lang)
    current = config.WORKSPACE_ROOT
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "request": request,
            "lang": lang,
            "strings": strings,
            "page_title": strings["setup.title"],
            "active_page": "setup",
            "current_workspace": str(current) if current else "",
            "default_workspace": str(DEFAULT_WORKSPACE),
            "message": message,
            "message_type": message_type,
        },
    )


@router.post("/setup")
async def setup_save(workspace: str = Form(...)):
    try:
        path = resolve_workspace_path(workspace)
        _save_workspace(path)
        config.reload_settings()
        return RedirectResponse(
            url=f"/submit?message={quote('workspace saved')}&message_type=success",
            status_code=303,
        )
    except (ValueError, ConfigError, OSError) as exc:
        return RedirectResponse(
            url=f"/setup?message={quote(str(exc))}&message_type=error",
            status_code=303,
        )
