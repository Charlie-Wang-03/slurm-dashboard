from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import CURRENT_USER, HOSTNAME

router = APIRouter()


@router.get("/health")
async def health():
    """Health check endpoint — returns 200 when the service is alive."""
    return JSONResponse(
        content={"status": "ok", "hostname": HOSTNAME, "user": CURRENT_USER}
    )


@router.get("/")
async def home(request: Request):
    return RedirectResponse(url="/status")
