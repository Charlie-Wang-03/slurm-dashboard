import os

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.database import init_db
from app.i18n import LANG_COOKIE, LANG_COOKIE_MAX_AGE, LANG_EN, LANG_ZH
from app.routers import env_check, home, jobs, setup, status, submit
from app.security import check_same_origin

app = FastAPI(title="slurm-dashboard")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# First-run wizard: until a workspace is configured, only the setup
# page (plus health and static assets) is reachable.
PUBLIC_PATHS = {"/health", "/setup", "/favicon.ico"}

# Manual UI language switch: ?lang=en|zh sets a year-long cookie and
# redirects to the same path without the query parameter, so the toggle
# is a plain link (no JavaScript) and the choice survives reloads.
LANG_OPTIONS = {LANG_EN, LANG_ZH}


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
        if origin and not check_same_origin(origin, request.headers.get("host", "")):
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
