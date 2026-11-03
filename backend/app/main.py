"""FastAPI-app. Endpoints för pipeline-stegen läggs till fas för fas (SPEC 13)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.review import router as review_router

app = FastAPI(title="VS-Kalkyl", version="0.1.0")
app.include_router(health_router)
app.include_router(review_router)

# Granskningsgränssnittet (SPEC 9): statisk React-sida utan byggsteg, frontend/index.html
_UI = Path(__file__).resolve().parents[2] / "frontend"
if _UI.exists():
    app.mount("/ui", StaticFiles(directory=_UI, html=True), name="ui")
