from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter()


@router.get("/health")
async def health():
    """Minimal liveness endpoint — intentionally exposes no host/user metadata."""
    return JSONResponse(content={"status": "ok"})


@router.get("/")
async def home(request: Request):
    return RedirectResponse(url="/status")
