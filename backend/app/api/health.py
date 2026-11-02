from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from app.config.settings import load_label_grammar, load_models_config, load_reference_tables, load_thresholds
from app.db.session import get_engine

router = APIRouter()


def engine_dep() -> Engine:
    return get_engine()


@router.get("/health")
def health(engine: Engine = Depends(engine_dep)) -> JSONResponse:  # noqa: B008
    checks: dict[str, Any] = {}
    try:
        load_models_config()
        load_label_grammar()
        load_reference_tables()
        load_thresholds()
        checks["config"] = "ok"
    except Exception as exc:
        checks["config"] = f"fel: {exc}"
    try:
        with engine.connect() as conn:
            exts = set(conn.scalars(text("SELECT extname FROM pg_extension")).all())
        missing = {"postgis", "pg_trgm"} - exts
        checks["database"] = "ok" if not missing else f"saknar extension: {sorted(missing)}"
    except Exception as exc:
        checks["database"] = f"fel: {type(exc).__name__}"
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks}, status_code=200 if healthy else 503
    )
