"""Hela flödet på ett projekt, från uppladdade filer till exportfiler (SPEC 13 fas 12, `make demo`).

    python -m app.pipeline.demo INDATA_KATALOG UT_KATALOG [--register REGISTER.csv] [--no-ai] [--save]

INDATA_KATALOG innehåller förfrågningsunderlaget (TB och ritningar, PDF eller ZIP). Utdata:
  artikellista.xlsx, avvikelser.md, mangdlista.xlsx, markerad.pdf, prixel.xlsx, prixel_urklipp.txt,
  forfragningar/*.eml, sammanfattning.md
Inget skickas: mailen är utkast. Ritningsdelen kräver vvs_engine (VVS_ENGINE_CMD); saknas den hoppas den över
och
sammanfattningen säger det. AI-anrop loggas i ai_run och cachas – en andra körning kostar inget.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.ai.client import AIClient
from app.articles.match import MemoryArticleSource
from app.articles.pipeline import match_items, positions
from app.articles.register import read_register
from app.config.settings import load_models_config
from app.db.session import make_session_factory
from app.drawings.checks import declared_scale_for_page
from app.drawings.context import drawing_context
from app.drawings.estimates import fittings, insulation
from app.drawings.legend_tables import read_tables
from app.drawings.quantities import summarize, summarize_outside
from app.drawings.source import DrawingSourceError
from app.drawings.vvs_engine import VvsEngineSource
from app.export.marked_pdf import marked_pdf, quantity_xlsx
from app.export.prixel import ClipboardExporter, ExcelExporter
from app.ingest.pdf_typed import open_pdf, page_text
from app.pipeline.phase1 import analyze_files, cross_check, load_inputs
from app.requests.supplier import build_requests, compose, to_eml
from app.rules.engine import RuleContext, run_rules
from app.tb.extract import extract_tb
from app.tb.header import project_info
from app.tb.system_materials import SystemMaterialIndex, from_designations, from_tb_pages


def _xlsx(header: list[str], rows: list[list[Any]], title: str) -> bytes:
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = title
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def run(inputs: Path, out: Path, register: Path | None, use_ai: bool) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    # tak per körning = projektets kostnadstak (models.yaml), så att en uppladdning aldrig kan dra iväg
    ai = (
        AIClient(make_session_factory(), budget_usd=load_models_config().cost_cap_usd_per_project)
        if use_ai
        else None
    )
    files = sorted(p for p in inputs.iterdir() if p.suffix.lower() in (".pdf", ".zip"))
    p1 = analyze_files(load_inputs(files), ai)
    summary: dict[str, Any] = {"documents": [d.file.filename for d in p1.documents], "notes": []}
    tb_doc = next((d for d in p1.documents if d.kind == "tb"), None)
    tb = None
    if tb_doc is not None:
        tb = extract_tb(tb_doc.file.data, tb_doc.file.filename, ai)
    project = project_info(tb_doc.file.data, tb_doc.project_no) if tb_doc else None
    # ---------------------------------------------------------------- ritning
    draw_doc = next(
        (d for d in p1.documents if any(p.kind.kind in ("plan", "schematic") for p in d.pages)), None
    )
    takeoff, ctx_d, q_rows, outside, tables, fit, ins = None, None, [], [], [], [], []
    if draw_doc is not None:
        plan_pages = {
            p.page_no
            for p in draw_doc.pages
            if p.kind.kind == "plan"
            and "purpose:demolition" not in (p.title_block.flags if p.title_block else [])
        }
        schem = {p.page_no for p in draw_doc.pages if p.kind.kind == "schematic"}
        pdf_path = out / "_indata" / Path(draw_doc.file.filename).name
        pdf_path.parent.mkdir(exist_ok=True)
        pdf_path.write_bytes(draw_doc.file.data)
        labels = out / "_arbetsfiler" / "t5_labels.json"
        labels.parent.mkdir(exist_ok=True)
        if use_ai and not labels.exists():
            pages = ",".join(str(n) for n in sorted(plan_pages | schem))
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.drawings.labels",
                    str(pdf_path),
                    "--pages",
                    pages,
                    "--out",
                    str(labels),
                ],
                check=False,
                capture_output=True,
            )
        try:
            if not os.environ.get("VVS_ENGINE_CMD"):
                raise DrawingSourceError("VVS_ENGINE_CMD är inte satt – ritningsdelen hoppas över")
            takeoff = VvsEngineSource().analyze(
                pdf_path, out / "_arbetsfiler", labels=labels if labels.exists() else None
            )
        except DrawingSourceError as exc:
            summary["notes"].append(f"Ritning: {exc}")
        if takeoff is not None:
            declared = {
                p.page_no: declared_scale_for_page(
                    p.title_block.scales if p.title_block else [], p.features.paper_size
                )
                for p in draw_doc.pages
            }
            ctx_d = drawing_context(takeoff, plan_pages, schem, declared)
            runs = [r for s in takeoff.sheets if s.page in plan_pages for r in s.pipe_runs]
            tb_pages: list[tuple[int, str]] = []
            if tb_doc is not None:
                with open_pdf(tb_doc.file.data) as d:
                    tb_pages = [(i + 1, str(page_text(d[i]))) for i in range(len(d))]
            idx = SystemMaterialIndex.build(
                from_tb_pages(tb_pages), from_designations((r.page, r.designation) for r in runs)
            )
            known = {e.code for s in takeoff.sheets for e in s.legend}
            q_rows = summarize(runs, known_codes=known, system_materials=idx)
            outside = summarize_outside(
                o for s in takeoff.sheets if s.page in plan_pages for o in s.outside_contract
            )
            if use_ai and ai is not None and labels.exists():
                tables = read_tables(draw_doc.file.data, json.loads(labels.read_text(encoding="utf-8")), ai)
            engine_dir = out / "_arbetsfiler" / "vvs_engine"
            pipes = [
                p
                for sh in takeoff.sheets
                if sh.page in plan_pages
                for p in json.loads(
                    (engine_dir / "sheets" / str(sh.page - 1) / "physical-pipes.json").read_text(
                        encoding="utf-8"
                    )
                )["physical_pipes"]
            ]
            fit = fittings(pipes)
            ins = insulation(q_rows, tb.rules if tb else [], tables)
            (out / "markerad.pdf").write_bytes(
                marked_pdf(
                    draw_doc.file.data,
                    engine_dir,
                    takeoff,
                    q_rows,
                    project.name if project and project.name else "",
                )
            )
            (out / "mangdlista.xlsx").write_bytes(quantity_xlsx(q_rows, ins, fit, outside))
    # ---------------------------------------------------------------- artiklar, regler, förfrågningar
    matches = []
    if tb is not None and register is not None:
        reg = read_register(register.read_bytes(), register.name)
        matches = match_items(tb.all_items(), MemoryArticleSource(reg.rows), ai)
    ctx = RuleContext(
        tb=tb,
        document=tb_doc.file.filename if tb_doc else "TB",
        phase1=cross_check(p1),
        drawing_findings=ctx_d.findings if ctx_d else [],
        drawing_tags=ctx_d.plan_tags if ctx_d else {},
        drawing_pipe_labels=ctx_d.pipe_labels if ctx_d else [],
        quantity_flags=[(f"{r.system}-{r.dim}", f) for r in q_rows for f in r.flags],
        accessories=[m.accessory for m in matches if m.accessory],
    )
    devs = run_rules(ctx)
    dev_md = ["# Avvikelser", "", "| Grad | Regel | Meddelande | Fråga |", "| --- | --- | --- | --- |"]
    order = {"critical": 0, "warning": 1, "info": 2}
    for d in sorted(devs, key=lambda d: (order[d.effective_severity], d.rule_id)):
        dev_md.append(
            f"| {d.effective_severity} | {d.rule_id} | {d.message.replace('|', '/')} | "
            f"{(d.question or '').replace('|', '/')} |"
        )
    (out / "avvikelser.md").write_text("\n".join(dev_md) + "\n", encoding="utf-8")
    if tb is not None and matches:
        items = tb.all_items()
        goods = [it for it in items if it.kind == "object"]
        rows = [
            [
                it.parent_designation or it.designation,
                it.description,
                float(it.quantity) if it.quantity else None,
                it.unit,
                m.outcome,
                m.article.dahl_art_no if m.article else None,
                m.method,
                round(m.score, 2),
                m.reason,
            ]
            for it, m in zip(goods, matches, strict=True)
        ]
        (out / "artikellista.xlsx").write_bytes(
            _xlsx(
                [
                    "Position",
                    "Produkt",
                    "Antal",
                    "Enhet",
                    "Utfall",
                    "Artikel",
                    "Metod",
                    "Score",
                    "Motivering",
                ],
                rows,
                "Artiklar",
            )
        )
        pos = positions(items, matches)
        (out / "prixel.xlsx").write_bytes(ExcelExporter().export(pos))
        (out / "prixel_urklipp.txt").write_bytes(ClipboardExporter().export(pos))
        mail_dir = out / "forfragningar"
        mail_dir.mkdir(exist_ok=True)
        if project is not None:
            for d in build_requests(items, matches, devs, project):
                compose(d, ai)
                (mail_dir / f"{d.supplier}.eml".replace("/", "_")).write_bytes(to_eml(d))
    # ---------------------------------------------------------------- paket för granskningsgränssnittet
    import dataclasses
    import uuid as _uuid

    def ident(*parts: object) -> str:
        return str(_uuid.uuid5(_uuid.NAMESPACE_URL, "vs-kalkyl:" + ":".join(map(str, parts))))

    def plain(o: Any) -> Any:
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return {k: plain(v) for k, v in dataclasses.asdict(o).items()}
        if hasattr(o, "model_dump"):
            return plain(o.model_dump())
        if isinstance(o, dict):
            return {str(k): plain(v) for k, v in o.items()}
        if isinstance(o, list | tuple | set):
            return [plain(v) for v in o]
        if isinstance(o, Path):
            return str(o)
        if o is None or isinstance(o, str | int | float | bool):
            return o
        return str(o)

    items_out = []
    for it in tb.all_items() if tb else []:
        d = plain(dataclasses.replace(it, children=[]))
        d["id"] = ident("item", it.parent_designation, it.designation, it.description)
        items_out.append(d)
    goods = [it for it in tb.all_items() if it.kind == "object"] if tb else []
    bundle = {
        "project": plain(project) if project else {},
        "documents": [
            {
                "filename": Path(d.file.filename).name,
                "pages": len(d.pages),
                "kinds": [p.kind.kind for p in d.pages],
            }
            for d in p1.documents
        ],
        "items": items_out,
        "rules": plain(tb.rules) if tb else [],
        "deviations": [
            {**plain(d), "id": ident("dev", d.rule_id, d.message), "severity": d.effective_severity}
            for d in devs
        ],
        "quantities": [{**plain(r), "id": ident("qty", r.system, r.material, r.dim)} for r in q_rows],
        "outside_contract": plain(outside),
        "insulation": plain(ins),
        "fittings": plain(fit),
        "legend_tables": plain(tables),
        "sheets": [
            {"page": sh.page, "coverage": plain(sh.coverage), "scale": plain(sh.scale)}
            for sh in (takeoff.sheets if takeoff else [])
        ],
        "matches": [
            {
                "id": ident("match", it.parent_designation, it.designation, it.description),
                "position": it.parent_designation or it.designation,
                "product": it.description,
                "outcome": m.outcome,
                "article": plain(m.article),
                "method": m.method,
                "score": m.score,
                "reason": m.reason,
                "refs": it.source_refs,
            }
            for it, m in zip(goods, matches, strict=False)
        ],
        "requests": sorted(p.name for p in (out / "forfragningar").glob("*.eml"))
        if (out / "forfragningar").exists()
        else [],
        "exports": sorted(p.name for p in out.iterdir() if p.is_file() and p.name != "bundle.json"),
        "drawing_pdf": Path(draw_doc.file.filename).name if draw_doc else None,
        "tb_pdf": Path(tb_doc.file.filename).name if tb_doc else None,
    }
    if tb_doc is not None:
        (out / "_indata" / Path(tb_doc.file.filename).name).parent.mkdir(exist_ok=True)
        (out / "_indata" / Path(tb_doc.file.filename).name).write_bytes(tb_doc.file.data)
    (out / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    summary.update(
        {
            "tb_items": len(tb.all_items()) if tb else 0,
            "deviations": len(devs),
            "pipe_rows": len(q_rows),
            "pipe_metres": round(sum(r.length_m for r in q_rows), 2),
            "outside_contract_m": round(sum(o.length_m for o in outside), 2),
            "ai_spent_usd": float(ai.spent_usd) if ai else 0.0,
        }
    )
    md = [
        "# Sammanfattning",
        "",
        f"Projekt: {project.name if project else '–'} – {project.customer if project else ''}",
        "",
        *[f"- {k}: {v}" for k, v in summary.items() if k != "notes"],
        "",
        *[f"Obs: {n}" for n in summary["notes"]],
    ]
    (out / "sammanfattning.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--register", type=Path)
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args(argv)
    s = run(args.inputs, args.out, args.register, not args.no_ai)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
