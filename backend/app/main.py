"""FastAPI-app. Endpoints för pipeline-stegen läggs till fas för fas (SPEC 13)."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.health import router as health_router

app = FastAPI(title="VS-Kalkyl", version="0.1.0")
app.include_router(health_router)
