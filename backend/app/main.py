"""Kaksha Saathi API. Run: uvicorn app.main:app  (from backend/)."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import parent, parent_insights, setup, teacher, voice
from app.config import get_settings
from app.db import init_db
from app.services.content import get_content, load_custom_checkpoints


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    get_content()  # fail fast on bad content
    load_custom_checkpoints()  # teacher-made topics become real checkpoints (single-worker registry)
    if get_settings().seed_on_startup:
        from app.seed import reseed_demo_if_outdated, seed_if_empty
        seed_if_empty()  # demo school on a fresh database only
        try:  # the live DB is persistent: refresh the DEMO school once when its demo story changes
            reseed_demo_if_outdated()
        except Exception:  # never let a demo refresh stop the API from starting
            logging.getLogger("kaksha").exception("demo re-seed failed; serving the existing data")
    yield


app = FastAPI(
    title="Kaksha Saathi API",
    version="1.0.0",
    description="Continuous learning-gap and intervention system for primary classrooms. "
                "Teacher app: diagnosis → groups → intervention → reassessment. "
                "Parent app: structured voice practice from the same learning map.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-response-ms"],
)


@app.middleware("http")
async def timing(request: Request, call_next):
    t0 = time.monotonic()
    resp = await call_next(request)
    resp.headers["x-response-ms"] = str(int((time.monotonic() - t0) * 1000))
    return resp


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/readyz")
def readyz():
    c = get_content()
    return {"ok": True, "checkpoints": len(c.checkpoints), "activities": len(c.activities)}


app.include_router(teacher.router)
app.include_router(setup.router)
app.include_router(parent.router)
app.include_router(parent_insights.router)
app.include_router(voice.router)

# Mounted AFTER every route: serves the landing page at "/" and the two Flutter web builds.
WEB_DIR = Path(__file__).resolve().parents[2] / "deploy" / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
