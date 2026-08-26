import os

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.database import init_db
from app.i18n import LANG_COOKIE, LANG_COOKIE_MAX_AGE, LANG_EN, LANG_ZH
from app.routers import env_check, home, jobs, setup, status, submit
from app.security import check_loopback_host, check_same_origin

# This is a local teaching UI rather than a public API. Disable the default
# FastAPI schema/docs endpoints to keep the reachable surface minimal.
app = FastAPI(
    title="slurm-dashboard",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# First-run wizard: until a workspace is configured, only the setup
# page (plus health and static assets) is reachable.
PUBLIC_PATHS = {"/health", "/setup", "/favicon.ico"}

# Manual UI language switch: ?lang=en|zh sets a year-long cookie and
# redirects to the same path without the query parameter, so the toggle
# is a plain link (no JavaScript) and the choice survives reloads.
LANG_OPTIONS = {LANG_EN, LANG_ZH}

# Browser forms in this teaching UI are tiny. Keep an application-level
# ceiling above the 1 MiB script limit so normal multipart overhead fits.
MAX_REQUEST_BYTES = 2 * 1024 * 1024


@app.middleware("http")
async def first_run_guard(request, call_next):
    path = request.url.path
    if (
        config.WORKSPACE_ROOT is None
        and path not in PUBLIC_PATHS
        and not path.startswith("/static")
    ):
        return RedirectResponse(url="/setup", status_code=303)
    return await call_next(request)


@app.middleware("http")
async def csrf_origin_guard(request, call_next):
    """Block cross-site state-changing requests.

    Binding to 127.0.0.1 does not stop cross-site form posts: a website
    the owner visits while an SSH tunnel is open can POST to this port
    (form submissions are not subject to CORS or Private Network
    Access). Browsers send an Origin header on POSTs; non-browser
    clients (curl, cron, tests) do not. Accept same-origin loopback
    posts, reject everything else, allow requests without Origin.
    """
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request.url.path.startswith("/static"):
        origin = request.headers.get("origin")
        if origin and not check_same_origin(
            origin,
            request.headers.get("host", ""),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
        ):
            return Response(status_code=403, content="cross-origin request blocked")
    return await call_next(request)


@app.middleware("http")
async def language_switch(request, call_next):
    if request.method == "GET" and not request.url.path.startswith("/static"):
        lang = request.query_params.get("lang")
        if lang in LANG_OPTIONS:
            response = RedirectResponse(
                url=request.url.replace(query=""), status_code=303
            )
            response.set_cookie(
                LANG_COOKIE, lang, max_age=LANG_COOKIE_MAX_AGE, samesite="lax"
            )
            return response
    return await call_next(request)


@app.middleware("http")
async def request_size_guard(request, call_next):
    """Reject clearly oversized state-changing requests before form parsing."""
    if request.method in {"POST", "PUT", "PATCH"}:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                return Response(status_code=400, content="invalid content-length")
            if size < 0:
                return Response(status_code=400, content="invalid content-length")
            if size > MAX_REQUEST_BYTES:
                return Response(status_code=413, content="request too large")
    return await call_next(request)


@app.middleware("http")
async def loopback_host_guard(request, call_next):
    """Reject non-loopback Host headers on every route and HTTP method.

    Loopback binding alone does not prevent DNS rebinding. Requiring the
    browser-visible Host itself to be localhost / a loopback IP closes the
    read-side rebinding path as well as protecting state-changing routes.
    """
    if not check_loopback_host(request.headers.get("host", "")):
        return Response(status_code=403, content="non-loopback host blocked")
    return await call_next(request)


@app.middleware("http")
async def security_headers(request, call_next):
    """Apply small, dependency-free browser hardening headers."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.on_event("startup")
async def startup_event():
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    init_db()


app.include_router(home.router)
app.include_router(status.router)
app.include_router(submit.router)
app.include_router(jobs.router)
app.include_router(env_check.router)
app.include_router(setup.router)
