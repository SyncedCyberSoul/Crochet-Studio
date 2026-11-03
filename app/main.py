from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .auth import read_session
from .backup import start_scheduler
from .config import APP_DIR, settings
from .db import engine, init_db
from .models import User
from .routers import admin, discover, ideas, models3d, patterns, profiles, projects, stash, stitches


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    stop_backups = start_scheduler()
    yield
    stop_backups.set()


settings.media_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Crochet Studio", lifespan=lifespan, docs_url=None, redoc_url=None)

# Reachable without picking a profile.
OPEN_PATHS = ("/static/", "/profiles", "/admin/login", "/admin/setup", "/favicon.ico", "/media/avatars/",
              "/manifest.webmanifest", "/sw.js")


def _bounce(request: Request, url: str) -> Response:
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@app.middleware("http")
async def profile_gate(request: Request, call_next):
    data = read_session(request)
    request.state.is_admin = bool(data.get("admin"))
    request.state.user = None
    if uid := data.get("uid"):
        with Session(engine) as session:
            user = session.get(User, uid)
            if user:
                session.expunge(user)
                request.state.user = user

    path = request.url.path
    if path.startswith("/admin") and not path.startswith(("/admin/login", "/admin/setup")):
        if not request.state.is_admin:
            return _bounce(request, "/admin/login")
    elif not path.startswith(OPEN_PATHS) and request.state.user is None:
        target = "/profiles" if path == "/" else f"/profiles?next={quote(str(request.url.path))}"
        return _bounce(request, target)
    elif (request.state.user and not request.state.user.has_password and not request.state.is_admin
          and not path.startswith(OPEN_PATHS + ("/set-password", "/logout"))):
        # The site is on the internet: a profile must have a password before anything else opens.
        return _bounce(request, "/set-password")
    return await call_next(request)


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(APP_DIR / "static" / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the root so it may control every page ("Add to Home Screen" needs one).
    return FileResponse(APP_DIR / "static" / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
for module in (profiles, admin, projects, patterns, ideas, discover, models3d, stash, stitches):
    app.include_router(module.router)
