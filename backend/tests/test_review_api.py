"""Granskningsgränssnittets API (SPEC 9): projekt, sidbild, filer, korrigeringar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ingest.pdf_typed import new_pdf, pdf_bytes
from app.main import app


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "proj"
    (d / "_indata").mkdir(parents=True)
    doc = new_pdf()
    doc.new_page(width=200, height=100)
    (d / "_indata" / "tb.pdf").write_bytes(pdf_bytes(doc))
    (d / "prixel.xlsx").write_bytes(b"x")
    bundle = {
        "project": {"name": "Testhall"},
        "items": [],
        "deviations": [],
        "documents": [],
        "quantities": [],
        "matches": [],
        "requests": [],
        "exports": ["prixel.xlsx"],
        "sheets": [],
    }
    (d / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setenv("VSK_PROJECTS_DIR", str(tmp_path))
    return d


def test_projects_page_and_files(project: Path) -> None:
    c = TestClient(app)
    assert c.get("/api/projects").json()[0]["name"] == "Testhall"
    assert c.get("/api/projects/proj").json()["exports"] == ["prixel.xlsx"]
    r = c.get("/api/projects/proj/pages/tb.pdf/1.png")
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert c.get("/api/projects/proj/files/prixel.xlsx").content == b"x"
    assert c.get("/api/projects/proj/files/..%2Fbundle.json").status_code in (400, 404)
    assert c.get("/api/projects/nej").status_code == 404


def test_corrections_are_logged(project: Path) -> None:
    c = TestClient(app)
    body = {
        "entity": "item",
        "entity_id": "00000000-0000-0000-0000-000000000001",
        "field": "quantity",
        "old": 1,
        "new": 2,
    }
    assert c.post("/api/projects/proj/corrections", json=body).json()["ok"]
    assert c.get("/api/projects/proj").json()["corrections"][0]["new"] == 2


def test_the_start_page_is_the_review_ui() -> None:
    r = TestClient(app).get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] in ("/ui/", "/docs")
    assert TestClient(app).get("/ui/").status_code == 200


def test_no_projects_is_an_empty_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VSK_PROJECTS_DIR", str(tmp_path / "saknas"))
    assert TestClient(app).get("/api/projects").json() == []


def _auth(pw: str) -> dict[str, str]:
    import base64

    return {"Authorization": "Basic " + base64.b64encode(f"anna:{pw}".encode()).decode()}


def test_with_a_password_everything_but_health_needs_login(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VSK_ACCESS_PASSWORD", "hemligt")
    c = TestClient(app)
    assert c.get("/api/projects").status_code == 401
    assert c.get("/api/projects", headers=_auth("fel")).status_code == 401
    assert c.get("/api/projects", headers=_auth("hemligt")).status_code == 200
    assert c.get("/health").status_code in (200, 503)  # hälsokontrollen är öppen


def test_upload_is_refused_without_a_password(project: Path) -> None:
    r = TestClient(app).post(
        "/api/projects", data={"name": "X"}, files=[("files", ("tb.pdf", b"%PDF-1.7", "a"))]
    )
    assert r.status_code == 403 and "VSK_ACCESS_PASSWORD" in r.json()["detail"]


def test_upload_runs_the_flow_in_the_background(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    import app.pipeline.demo as demo

    monkeypatch.setenv("VSK_ACCESS_PASSWORD", "hemligt")
    seen: dict[str, Any] = {}

    def fake_run(inputs: Path, out: Path, register: Path | None, use_ai: bool) -> dict[str, Any]:
        seen["files"] = sorted(p.name for p in inputs.iterdir())
        seen["register"] = register.name if register else None
        (out / "bundle.json").write_text(
            json.dumps({"project": {"name": "Ny"}, "items": [], "deviations": []})
        )
        return {"notes": []}

    monkeypatch.setattr(demo, "run", fake_run)
    c = TestClient(app)
    files = [
        ("files", ("Teknisk beskrivning & VS.pdf", b"%PDF-1.7 x", "application/pdf")),
        ("register", ("reg.csv", b"a;b", "text/csv")),
    ]
    r = c.post("/api/projects", data={"name": "Ny hall"}, files=files, headers=_auth("hemligt"))
    assert r.status_code == 200
    pid = r.json()["id"]
    for _ in range(50):
        if c.get(f"/api/projects/{pid}/status", headers=_auth("hemligt")).json().get("state") == "done":
            break
        time.sleep(0.05)
    assert c.get(f"/api/projects/{pid}/status", headers=_auth("hemligt")).json()["state"] == "done"
    assert seen == {"files": ["Teknisk beskrivning _ VS.pdf"], "register": "reg.csv"}  # namnet tvättat
    bad = c.post(
        "/api/projects",
        data={"name": "Y"},
        files=[("files", ("a.exe", b"MZ..", "x"))],
        headers=_auth("hemligt"),
    )
    assert bad.status_code == 400
