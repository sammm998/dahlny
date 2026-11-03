"""FastAPI-app. Endpoints för pipeline-stegen läggs till fas för fas (SPEC 13)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import AccessMiddleware
from app.api.health import router as health_router
from app.api.review import router as review_router

app = FastAPI(title="VS-Kalkyl", version="0.1.0")
app.add_middleware(AccessMiddleware)
app.include_router(health_router)
app.include_router(review_router)

# Granskningsgränssnittet (SPEC 9): statisk React-sida utan byggsteg, frontend/index.html.
# I repot ligger den bredvid backend/; i containern i /app/frontend (VSK_UI_DIR).
_UI = Path(os.environ.get("VSK_UI_DIR", Path(__file__).resolve().parents[2] / "frontend"))
if _UI.exists():
    app.mount("/ui", StaticFiles(directory=_UI, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Startsidan är granskningsgränssnittet (API:t finns under /api och /docs)."""
    return RedirectResponse("/ui/" if _UI.exists() else "/docs")
