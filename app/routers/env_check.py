from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.env_check import get_all_checks
from app.config import get_settings
from app.i18n import detect_language, get_strings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/env-check", response_class=HTMLResponse)
async def env_check(request: Request):
    data = get_all_checks()
    data["check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lang = detect_language(request, get_settings().ui_lang)
    strings = get_strings(lang)
    return templates.TemplateResponse(
        request,
        "env_check.html",
        {
            "request": request,
            "lang": lang,
            "strings": strings,
            "page_title": strings["env.title"],
            "active_page": "env-check",
            **data,
        },
    )


@router.get("/diagnostics")
async def diagnostics_redirect():
    return RedirectResponse(url="/env-check")
