from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.health import engine_dep
from app.main import app


def test_health_ok_against_test_database(db_engine: Engine) -> None:
    app.dependency_overrides[engine_dep] = lambda: db_engine
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.json()
    assert response.json() == {"status": "ok", "checks": {"config": "ok", "database": "ok"}}
