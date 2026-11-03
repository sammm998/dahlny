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
import threading
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.api.auth import uploads_allowed, user_of
from app.ingest.pdf_typed import open_pdf, png_bytes

router = APIRouter(prefix="/api")
REPO = Path(__file__).resolve().parents[3]
SAFE = re.compile(r"^[A-Za-z0-9ÅÄÖåäö _.,()-]+$")
PAGE_DPI = 110


def projects_dir() -> Path:
    return Path(os.environ.get("VSK_PROJECTS_DIR", REPO / "demo"))


def _projects(with_jobs: bool = False) -> dict[str, Path]:
    """Projektkatalogerna: med bundle.json (färdiga), och med with_jobs även de som körs (status.json)."""
    root = projects_dir()
    if (root / "bundle.json").exists():
        return {root.name: root}
    if not root.exists():
        return {}
    marker = ("bundle.json", "status.json") if with_jobs else ("bundle.json",)
    return {p.name: p for p in sorted(root.iterdir()) if any((p / m).exists() for m in marker)}


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
    for pid, d in _projects(with_jobs=True).items():
        if not (d / "bundle.json").exists():
            st = _status(d)
            out.append(
                {"id": pid, "name": st.get("name"), "state": st.get("state"), "deviations": 0, "items": 0}
            )
            continue
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


# --------------------------------------------------------------------------- uppladdning och körning på
# servern

MAX_UPLOAD_MB = float(os.environ.get("VSK_MAX_UPLOAD_MB", "300"))
_jobs_lock = threading.Lock()


def _status(d: Path) -> dict[str, Any]:
    p = d / "status.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _set_status(d: Path, **fields: Any) -> None:
    with _jobs_lock:
        st = {**_status(d), **fields}
        (d / "status.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def _ai_available() -> tuple[bool, str]:
    if not (os.environ.get("DAHLNY_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return False, "AI-nyckel saknas (DAHLNY_ANTHROPIC_API_KEY) – TB och etiketter läses inte"
    try:
        from sqlalchemy import text

        from app.db.session import get_engine

        with get_engine().connect() as c:
            c.execute(text("SELECT 1 FROM ai_run LIMIT 1"))
    except Exception as exc:
        return False, f"databasen för ai_run nås inte ({type(exc).__name__}) – AI-stegen hoppas över"
    return True, ""


def _run_job(d: Path, register: Path | None) -> None:
    from app.pipeline.demo import run

    use_ai, why = _ai_available()
    _set_status(d, state="running", started=datetime.now(UTC).isoformat(), notes=[why] if why else [])
    try:
        summary = run(d / "_uppladdat", d, register, use_ai)
        _set_status(
            d,
            state="done",
            finished=datetime.now(UTC).isoformat(),
            notes=[*([why] if why else []), *summary.get("notes", [])],
            summary=summary,
        )
    except Exception as exc:  # ett fel syns i gränssnittet, aldrig tyst
        _set_status(
            d,
            state="failed",
            finished=datetime.now(UTC).isoformat(),
            error=f"{type(exc).__name__}: {exc}",
            trace=traceback.format_exc()[-3000:],
        )


def _clean_name(name: str) -> str:
    """Filnamn ur en uppladdning: bara säkra tecken, aldrig en sökväg."""
    stem = re.sub(r"[^A-Za-z0-9ÅÄÖåäö _.,()-]", "_", Path(name).name).strip(" .") or "fil"
    return stem[:120]


def _slug(name: str) -> str:
    ascii_ = name.lower().translate(str.maketrans("åäöé", "aaoe"))
    base = re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-")[:40] or "projekt"
    return f"{base}-{uuid.uuid4().hex[:6]}"


@router.post("/projects")
async def create_project(
    request: Request,
    name: str = Form(...),
    files: list[UploadFile] = File(...),  # noqa: B008
    register: UploadFile | None = File(None),  # noqa: B008
) -> dict[str, Any]:
    """Laddar upp förfrågningsunderlaget (PDF/ZIP) och startar flödet i bakgrunden. Kräver inloggning."""
    if not uploads_allowed():
        raise HTTPException(
            403,
            "Uppladdning är avstängd: sätt VSK_ACCESS_PASSWORD så att underlaget skyddas av "
            "inloggning (kundmaterial läggs aldrig på en öppen adress).",
        )
    from app.ingest.files import detect_kind

    d = projects_dir() / _slug(name)
    up = d / "_uppladdat"
    up.mkdir(parents=True)
    total = 0.0
    for f in files:
        data = await f.read()
        total += len(data) / 1e6
        kind = detect_kind(data, f.filename or "")
        if kind not in ("pdf", "zip"):
            raise HTTPException(400, f"{f.filename}: bara PDF eller ZIP stöds här (fick {kind})")
        if total > MAX_UPLOAD_MB:
            raise HTTPException(413, f"Underlaget är större än {MAX_UPLOAD_MB:.0f} MB")
        (up / _clean_name(f.filename or "fil.pdf")).write_bytes(data)
    reg_path = None
    if register is not None and register.filename:
        reg_path = d / _clean_name(register.filename)
        reg_path.write_bytes(await register.read())
    _set_status(
        d,
        name=name,
        state="queued",
        created_by=user_of(request) or "granskare",
        files=sorted(p.name for p in up.iterdir()),
        register=reg_path.name if reg_path else None,
    )
    threading.Thread(target=_run_job, args=(d, reg_path), daemon=True).start()
    return {"id": d.name, "state": "queued"}


@router.get("/projects/{pid}/status")
def project_status(pid: str) -> dict[str, Any]:
    d = _projects(with_jobs=True).get(pid)
    if d is None:
        raise HTTPException(404, f"Projektet {pid} finns inte")
    st = _status(d)
    st.pop("trace", None)
    return st


@router.get("/config")
def ui_config() -> dict[str, Any]:
    ai, why = _ai_available()
    return {
        "uploads": uploads_allowed(),
        "ai": ai,
        "ai_note": why,
        "drawings": bool(os.environ.get("VVS_ENGINE_CMD")),
    }
