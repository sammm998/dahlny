"""API för granskningsgränssnittet (SPEC 9).

Ett projekt är en körning av flödet (`python -m app.pipeline.demo … UT`), vars `bundle.json` bär allt med
källhänvisningar. Katalogen med projekt anges i `VSK_PROJECTS_DIR` (standard: `demo/` i repot – en katalog per
projekt, eller själva katalogen om den har en bundle.json).

- GET  /api/projects                       – projekten
- GET  /api/projects/{pid}                 – hela paketet
- GET  /api/projects/{pid}/pages/{doc}/{n}.png – sidan som bild (för källa och ritningsvy)
- GET  /api/projects/{pid}/files/{name}    – en exportfil (markerad PDF, Excel, .eml …)
- POST /api/projects/{pid}/corrections     – en korrigering → tabellen `correction` (och correction-loggen i
paketet)

Inget skickas härifrån: exportfilerna laddas ned, mailen är utkast.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.ingest.pdf_typed import open_pdf, png_bytes

router = APIRouter(prefix="/api")
REPO = Path(__file__).resolve().parents[3]
SAFE = re.compile(r"^[A-Za-z0-9ÅÄÖåäö _.,()-]+$")
PAGE_DPI = 110


def projects_dir() -> Path:
    return Path(os.environ.get("VSK_PROJECTS_DIR", REPO / "demo"))


def _projects() -> dict[str, Path]:
    root = projects_dir()
    if (root / "bundle.json").exists():
        return {root.name: root}
    return (
        {p.name: p for p in sorted(root.iterdir()) if (p / "bundle.json").exists()} if root.exists() else {}
    )


def _dir(pid: str) -> Path:
    d = _projects().get(pid)
    if d is None:
        raise HTTPException(404, f"Projektet {pid} finns inte")
    return d


def _safe(name: str) -> str:
    if not SAFE.match(name) or ".." in name:
        raise HTTPException(400, "Ogiltigt filnamn")
    return name


@router.get("/projects")
def list_projects() -> list[dict[str, Any]]:
    out = []
    for pid, d in _projects().items():
        b = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
        out.append(
            {
                "id": pid,
                "name": (b.get("project") or {}).get("name"),
                "customer": (b.get("project") or {}).get("customer"),
                "deviations": len(b.get("deviations", [])),
                "items": len(b.get("items", [])),
            }
        )
    return out


@router.get("/projects/{pid}")
def get_project(pid: str) -> dict[str, Any]:
    d = _dir(pid)
    b: dict[str, Any] = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
    log = d / "corrections.json"
    b["corrections"] = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
    return b


@router.get("/projects/{pid}/pages/{doc}/{page}.png")
def page_png(pid: str, doc: str, page: int) -> Response:
    pdf = _dir(pid) / "_indata" / _safe(doc)
    if not pdf.exists():
        raise HTTPException(404, "Dokumentet finns inte i projektet")
    with open_pdf(pdf.read_bytes()) as d:
        if not 1 <= page <= len(d):
            raise HTTPException(404, "Sidan finns inte")
        pix = d[page - 1].get_pixmap(dpi=PAGE_DPI)
        return Response(png_bytes(pix), media_type="image/png", headers={"X-Scale": str(PAGE_DPI / 72)})


@router.get("/projects/{pid}/files/{name:path}")
def get_file(pid: str, name: str) -> FileResponse:
    d = _dir(pid)
    parts = [_safe(p) for p in name.split("/")]
    path = d.joinpath(*parts)
    if not path.is_file():
        raise HTTPException(404, "Filen finns inte")
    return FileResponse(path, filename=path.name)


class CorrectionIn(BaseModel):
    entity: str  # item | quantity | deviation | match
    entity_id: str
    field: str
    old: Any = None
    new: Any = None
    user: str = "granskare"


@router.post("/projects/{pid}/corrections")
def add_correction(pid: str, c: CorrectionIn) -> dict[str, Any]:
    """Sparar korrigeringen i projektets logg och, om databasen nås, i tabellen `correction` (SPEC 5, 9)."""
    d = _dir(pid)
    entry = {**c.model_dump(), "at": datetime.now(UTC).isoformat()}
    log = d / "corrections.json"
    entries = json.loads(log.read_text(encoding="utf-8")) if log.exists() else []
    entries.append(entry)
    log.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    stored = False
    try:
        from app.db.models import Correction, Project
        from app.db.session import make_session_factory

        b = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
        pid_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"vs-kalkyl-project:{pid}")
        with make_session_factory()() as s:
            if s.get(Project, pid_uuid) is None:
                proj = b.get("project") or {}
                s.add(
                    Project(
                        id=pid_uuid,
                        name=proj.get("name") or pid,
                        customer=proj.get("customer"),
                        project_no=proj.get("project_no"),
                        consultant=proj.get("consultant"),
                    )
                )
            s.add(
                Correction(
                    id=uuid.uuid4(),
                    project_id=pid_uuid,
                    entity=c.entity,
                    entity_id=uuid.UUID(c.entity_id),
                    field=c.field,
                    old={"value": c.old},
                    new={"value": c.new},
                    user=c.user,
                )
            )
            s.commit()
            stored = True
    except Exception as exc:  # databasen är valfri för granskningen – loggen i paketet räcker
        entry["db_error"] = type(exc).__name__
    return {"ok": True, "stored_in_db": stored, "count": len(entries)}
