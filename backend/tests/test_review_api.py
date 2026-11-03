"""Granskningsgränssnittets API (SPEC 9): projekt, sidbild, filer, korrigeringar."""

from __future__ import annotations

import json
from pathlib import Path

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
