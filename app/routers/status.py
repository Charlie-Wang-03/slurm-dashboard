from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.cluster_status import get_all_status
from app.config import get_settings
from app.gpu_history import VALID_MODES, VALID_SCALES, aggregate_gpu_data
from app.i18n import detect_language, get_strings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# The linear aggregator materializes time buckets in memory. Keep every
# browser/API request within a bounded teaching-scale window so crafted date
# parameters cannot allocate millions of buckets.
MAX_GPU_HISTORY_RANGE_DAYS = {
    "day": 31,
    "week": 366,
    "month": 366,
    "year": 3660,
}


def _parse_range_value(value: str, scale: str) -> datetime:
    value = value.strip()
    if scale == "day":
        return datetime.strptime(value, "%Y-%m-%d")
    if scale == "week":
        return datetime.strptime(f"{value}-1", "%G-W%V-%u")
    if scale == "month":
        return datetime.strptime(value, "%Y-%m")
    if scale == "year":
        return datetime.strptime(value, "%Y")
    raise ValueError("unsupported scale")


def _default_range_start(scale: str, now: datetime) -> datetime:
    if scale == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if scale == "week":
        return (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if scale == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def validate_gpu_history_range(scale: str, start: Optional[str], end: Optional[str]) -> None:
    """Reject reversed or excessively large query windows before aggregation."""
    now = datetime.now()
    start_dt = _parse_range_value(start, scale) if start else _default_range_start(scale, now)
    end_dt = _parse_range_value(end, scale) if end else now

    if end_dt < start_dt:
        raise ValueError("start must not be after end")

    max_days = MAX_GPU_HISTORY_RANGE_DAYS[scale]
    if end_dt - start_dt > timedelta(days=max_days):
        raise ValueError(f"requested {scale} range exceeds the {max_days}-day limit")


@router.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    data = get_all_status()
    lang = detect_language(request, get_settings().ui_lang)
    strings = get_strings(lang)
    # Load only the latest day summary for the overview cards; the charts
    # fetch their own data (any scale) from the JSON API.
    gpu_summary = aggregate_gpu_data("day", lang=lang)
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "request": request,
            "lang": lang,
            "strings": strings,
            "page_title": strings["status.title"],
            "active_page": "status",
            "gpu_overview": gpu_summary.get("data", {}).get("overview", {}),
            "has_gpu_data": len(gpu_summary.get("data", {}).get("timeline", [])) > 0,
            **data,
        },
    )


@router.get("/status/gpu-history")
async def gpu_history(
    request: Request,
    scale: str = Query("day", description="day / week / month / year"),
    mode: str = Query("linear", description="linear (timeline) / overlay (period-aligned)"),
    start: Optional[str] = Query(None, description="Start date, ISO format"),
    end: Optional[str] = Query(None, description="End date, ISO format"),
):
    """GPU usage history aggregated for the charts (JSON).

    Linear mode: start/end optional, defaults to the current scale window
    (day = today, week = this week, month = this month, year = this year).
    Overlay mode: start/end required to pin the comparison window.
    """
    if scale not in VALID_SCALES:
        scale = "day"
    if mode not in VALID_MODES:
        mode = "linear"

    if mode == "overlay" and (not start or not end):
        return JSONResponse(
            content={
                "scale": scale,
                "mode": mode,
                "error": "overlay mode requires start and end parameters",
            },
            status_code=400,
        )

    try:
        validate_gpu_history_range(scale, start, end)
        lang = detect_language(request, get_settings().ui_lang)
        data = aggregate_gpu_data(scale=scale, mode=mode, start=start, end=end, lang=lang)
        return JSONResponse(content=data)
    except ValueError as exc:
        return JSONResponse(
            content={
                "scale": scale,
                "mode": mode,
                "error": f"invalid date parameters: {exc}",
            },
            status_code=400,
        )
