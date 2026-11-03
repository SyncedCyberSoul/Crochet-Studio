from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import APP_DIR, settings
from .db import init_db
from .routers import projects


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


settings.media_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Crochet Studio", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
app.include_router(projects.router)
