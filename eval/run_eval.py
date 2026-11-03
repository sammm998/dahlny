"""`make eval` – utvärdering mot facitprojekten (SPEC 11).

Fas 0: läser och validerar facit (expected/*.json), kontrollerar indata mot MANIFEST.json och skriver en
rapport med måtten i SPEC 11.2. Mått vars pipeline-steg inte är byggt redovisas som "ej mätt (fas N)".
Varje fas kopplar in sin mätning här.

Avslutningskod: 0 = facit giltigt och indata (om de finns) stämmer; 1 = ogiltigt facit, fel hash eller
(med --require-inputs) saknade indata.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.evaluation.facit import InputManifest, ProjectFacit, load_facit, load_manifest

EVAL_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = EVAL_DIR / "projects"
REPORTS_DIR = EVAL_DIR / "reports"


@dataclass(frozen=True)
class Metric:
    name: str
    limit: str
    phase: int


# SPEC 11.2 – acceptansgränser v1, med den fas där mätningen kopplas in.
METRICS: tuple[Metric, ...] = (
    Metric("TB: recall på sakvaror", "≥ 98 %", 2),
    Metric("TB: precision (påhittade rader)", "≥ 99 %", 2),
    Metric("RSK/art.nr exakt korrekt", "100 %", 2),
    Metric("Antal korrekt", "≥ 99 %", 2),
    Metric("Artikelmatchning: rätt utfall", "≥ 95 %, resten osäker", 4),
    Metric("Etikettläsning tecken-exakt (vektor-PDF)", "≥ 98 %; resterande flaggade", 6),
    Metric("Andel otilldelad rörlängd", "≤ 2 % per sida", 7),
    Metric("Rörmeter per system×dim", "±3 % (horisontellt)", 7),
    Metric("Skala", "Två metoder inom 1 % eller blockerat", 7),
    Metric("Symbolantal", "100 % eller flaggat", 8),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_inputs(input_dir: Path, manifest: InputManifest) -> list[tuple[str, str]]:
    rows = []
    for f in manifest.files:
        path = input_dir / f.filename
        if not path.exists():
            rows.append((f.filename, "saknas lokalt"))
        elif sha256(path) != f.sha256:
            rows.append((f.filename, "FEL HASH – annan fil än facit avser"))
        else:
            rows.append((f.filename, "ok"))
    return rows


def facit_summary(facit: ProjectFacit) -> list[tuple[str, str]]:
    items = facit.spec_items.items
    labels = [lab for d in facit.labels.drawings for lab in d.labels]
    children = sum(1 for i in items if i.parent_designation)
    unknown = sum(1 for lab in labels if lab.parse_status == "unknown_token")
    return [
        ("SpecItems", f"{len(items)} ({children} barnposter)"),
        ("ProjectRules", str(len(facit.project_rules.rules))),
        (
            "Avvikelser",
            f"{len(facit.deviations.deviations)} (A.3 nr 1–13, nr 10 i två delar)",
        ),
        (
            "Etiketter",
            f"{len(labels)} på {len(facit.labels.drawings)} ritningar ({unknown} med okänd token)",
        ),
        (
            "Symbolantal",
            f"{len(facit.symbols.counts)} grupper, {len(facit.symbols.legend_tables)} legendtabeller",
        ),
    ]


def make_ai(use_ai: bool) -> tuple[Any, str]:
    """AIClient mot ai_run, eller None med skälet (--no-ai, databasen nås inte)."""
    if not use_ai:
        return None, "av (--no-ai)"
    from sqlalchemy.exc import OperationalError

    from app.ai.client import AIClient
    from app.config.settings import load_models_config
    from app.db.session import get_engine, make_session_factory

    try:
        with get_engine().connect():
            pass
    except OperationalError:
        return None, "av – databasen för ai_run nås inte (DATABASE_URL)"
    ai = AIClient(make_session_factory(), budget_usd=load_models_config().cost_cap_usd_per_project)
    return ai, "på (anrop loggas i ai_run; saknad nyckel syns som not_configured)"


def phase2_section(
    project_dir: Path, facit: ProjectFacit, ai: Any, results: dict[str, str], state: dict[str, Any]
) -> list[str]:
    """TB-extraktion (fas 2) mot spec_items.json och project_rules.json."""
    from app.evaluation.phase2 import report_lines, score_phase2
    from app.tb.extract import extract_tb

    tb = next((d for d in facit.pages.documents if d.kind == "tb"), None)
    if tb is None:
        return []
    if ai is None:
        return ["### Fas 2 – TB-extraktion", "", "ej mätt – kräver AI (T3/T4)", ""]
    result = extract_tb((project_dir / "input" / tb.filename).read_bytes(), tb.filename, ai)
    state["tb"] = result
    state["tb_document"] = tb.filename
    score = score_phase2(result, project_dir / "expected")
    rsk_ok, rsk_n = score.share("rsk_ok")
    art_ok, art_n = score.share("art_ok")
    qty_ok, qty_n = score.share("qty_ok")
    results["TB: recall på sakvaror"] = f"{100 * score.recall:.1f} %"
    results["TB: precision (påhittade rader)"] = (
        f"{100 * score.precision:.1f} % ({len(score.fabricated)} påhittade)"
    )
    results["RSK/art.nr exakt korrekt"] = f"RSK {rsk_ok}/{rsk_n}, art.nr {art_ok}/{art_n}"
    results["Antal korrekt"] = f"{qty_ok}/{qty_n}"
    return [*report_lines(score), ""]


def phase3_section(project_dir: Path, state: dict[str, Any]) -> list[str]:
    """Regelmotorn (fas 3) på fas 1:s korskontroller och TB-extraktionen, mot deviations.json."""
    from app.evaluation.phase3 import report_lines, score_deviations
    from app.pipeline.phase1 import cross_check
    from app.rules.engine import RuleContext, run_rules

    if "tb" not in state or "phase1" not in state:
        return []
    ctx = RuleContext(tb=state["tb"], document=state["tb_document"], phase1=cross_check(state["phase1"]))
    devs = run_rules(ctx)
    state["deviations"] = devs
    return [*report_lines(score_deviations(devs, project_dir / "expected", 3), devs), ""]


def phase4_section(project_dir: Path, ai: Any, results: dict[str, str], state: dict[str, Any]) -> list[str]:
    """Artikelmatchning mot projektets TESTDATA-register (fas 4) och ACCESSORY_NOT_CONFIRMED (A.3 nr 11)."""
    import json

    from app.articles.match import MemoryArticleSource
    from app.articles.pipeline import match_items, positions
    from app.articles.register import read_register
    from app.evaluation.phase2 import score_phase2
    from app.evaluation.phase3 import report_lines as dev_lines
    from app.evaluation.phase3 import score_deviations
    from app.evaluation.phase4 import report_lines, score_matching
    from app.export.prixel import ClipboardExporter, ExcelExporter
    from app.pipeline.phase1 import cross_check
    from app.rules.engine import RuleContext, run_rules

    facit_path = project_dir / "expected" / "matching.json"
    if "tb" not in state or not facit_path.exists():
        return []
    reg_file = project_dir / json.loads(facit_path.read_text(encoding="utf-8"))["register"]
    reg = read_register(reg_file.read_bytes(), reg_file.name)
    items = state["tb"].all_items()
    matches = match_items(items, MemoryArticleSource(reg.rows), ai)
    checks = score_matching(
        matches, score_phase2(state["tb"], project_dir / "expected").matched, project_dir / "expected"
    )
    ok = sum(c.verdict == "ok" for c in checks)
    unsure = sum(c.verdict == "osäker" for c in checks)
    results["Artikelmatchning: rätt utfall"] = (
        f"{100 * ok / len(checks):.1f} % ({ok}/{len(checks)}), {unsure} osäkra, "
        f"{len(checks) - ok - unsure} fel"
    )
    ctx = RuleContext(
        tb=state["tb"],
        document=state["tb_document"],
        phase1=cross_check(state["phase1"]),
        accessories=[m.accessory for m in matches if m.accessory],
    )
    devs = run_rules(ctx)
    state["matches"], state["deviations"] = matches, devs
    pos = positions(items, matches)
    out = REPORTS_DIR / project_dir.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "prixel.xlsx").write_bytes(ExcelExporter().export(pos))
    (out / "prixel_urklipp.txt").write_bytes(ClipboardExporter().export(pos))
    acc = [c for c in score_deviations(devs, project_dir / "expected", 4) if c.phase == 4]
    return [
        *report_lines(checks),
        "",
        *dev_lines(acc, [], "Fas 4 – avvikelser (A.3 nr 11)"),
        "",
        f"Prixel-export: `eval/reports/{project_dir.name}/prixel.xlsx` och `prixel_urklipp.txt`.",
        "",
    ]


def phase5_section(project_dir: Path, ai: Any, state: dict[str, Any]) -> list[str]:
    """Leverantörsförfrågningar (fas 5): utkast per leverantör som .eml. DoD: Furhoffs-utkastet för Bilaga A
    innehåller B201B, B202B, TS501 och frågorna."""
    from app.requests.supplier import build_requests, compose, to_eml
    from app.tb.header import project_info

    if "matches" not in state:
        return []
    tb_bytes = (project_dir / "input" / state["tb_document"]).read_bytes()
    project_no = next((d.project_no for d in state["phase1"].documents if d.project_no), None)
    drafts = build_requests(state["tb"].all_items(), state["matches"], state["deviations"],
                            project_info(tb_bytes, project_no))  # fmt: skip
    out = REPORTS_DIR / project_dir.name / "forfragningar"
    out.mkdir(parents=True, exist_ok=True)
    lines = ["### Fas 5 – leverantörsförfrågningar (utkast, skickas aldrig)", "",
             "| Leverantör | Rader | Frågor | Optioner | Text | Fil |",
             "| --- | --- | --- | --- | --- | --- |"]  # fmt: skip
    for d in drafts:
        compose(d, ai)
        name = f"{d.supplier}.eml".replace("/", "_")
        (out / name).write_bytes(to_eml(d))
        how = "mall (" + "; ".join(d.flags) + ")" if d.flags else "T9, kontrollerad"
        lines.append(f"| {d.supplier} | {', '.join(ln.designation for ln in d.lines)} | {len(d.questions)} | "
                     f"{len(d.options)} | {how} | `forfragningar/{name}` |")  # fmt: skip
    furhoffs = next((d for d in drafts if d.supplier.lower() == "furhoffs"), None)
    if furhoffs is not None:
        need = ["B201B", "B202B", "TS501"]
        ok = all(n in furhoffs.body_md for n in need) and len(furhoffs.questions) >= 2
        lines += [
            "",
            f"DoD fas 5 (Furhoffs-utkastet har {', '.join(need)} och frågorna): {'ok' if ok else '**NEJ**'}",
        ]
    return [*lines, ""]


def phase1_section(
    project_dir: Path, facit: ProjectFacit, ai: Any, ai_note: str, state: dict[str, Any]
) -> list[str]:
    """Kör fas 1 på projektets indata och jämför med pages.json (SPEC 13, fas 1 DoD)."""
    from app.evaluation.phase1 import score_phase1
    from app.pipeline.phase1 import analyze_files, load_inputs

    paths = [project_dir / "input" / d.filename for d in facit.pages.documents]
    result = analyze_files(load_inputs(paths), ai)
    state["phase1"] = result
    score = score_phase1(result, facit.pages)
    lines = [
        f"### Fas 1 – intag, sidklassning, titelblock ({score.passed}/{score.total})",
        "",
        f"AI: {ai_note}",
        "",
    ]
    lines += ["| Kontroll | Resultat | Facit | Fick |", "| --- | --- | --- | --- |"]
    for c in score.checks:
        lines.append(f"| {c.name} | {'ok' if c.ok else '**FEL**'} | {c.expected} | {c.got} |")
    lines.append("")
    return lines


def evaluate_project(project_dir: Path, require_inputs: bool, use_ai: bool = True) -> tuple[str, bool]:
    name = project_dir.name
    lines = [f"## {name}", ""]
    ok = True
    try:
        facit = load_facit(project_dir / "expected")
    except (ValidationError, FileNotFoundError) as exc:
        lines += ["**Facit ogiltigt eller saknas:**", "", "```", str(exc), "```", ""]
        return "\n".join(lines), False

    lines += ["### Facit", "", "| Del | Antal |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in facit_summary(facit)]
    lines.append("")

    lines += ["### Indata", "", "| Fil | Status |", "| --- | --- |"]
    try:
        input_rows = check_inputs(project_dir / "input", load_manifest(project_dir / "input"))
    except (ValidationError, FileNotFoundError) as exc:
        input_rows = [("MANIFEST.json", f"ogiltigt eller saknas: {exc}")]
        ok = False
    for filename, status in input_rows:
        lines.append(f"| `{filename}` | {status} |")
        if status.startswith("FEL") or (require_inputs and status != "ok"):
            ok = False
    lines.append("")

    results: dict[str, str] = {}
    if input_rows and all(status == "ok" for _, status in input_rows):
        ai, ai_note = make_ai(use_ai)
        state: dict[str, Any] = {}
        lines += phase1_section(project_dir, facit, ai, ai_note, state)
        lines += phase2_section(project_dir, facit, ai, results, state)
        lines += phase3_section(project_dir, state)
        lines += phase4_section(project_dir, ai, results, state)
        lines += phase5_section(project_dir, ai, state)
    else:
        lines += ["### Fas 1", "", "ej mätt – indatafilerna finns inte lokalt (se eval/README.md)", ""]

    lines += [
        "### Mått (SPEC 11.2)",
        "",
        "| Mått | Gräns | Resultat |",
        "| --- | --- | --- |",
    ]
    lines += [
        f"| {m.name} | {m.limit} | {results.get(m.name, f'ej mätt (fas {m.phase})')} |" for m in METRICS
    ]
    lines.append("")
    return "\n".join(lines), ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--project", action="append", help="Kör bara angivna projekt (namn på katalog)")
    parser.add_argument("--require-inputs", action="store_true", help="Saknade indatafiler ger fel")
    parser.add_argument("--projects-dir", type=Path, default=PROJECTS_DIR)
    parser.add_argument("--report", type=Path, default=REPORTS_DIR / "eval.md")
    parser.add_argument("--no-ai", action="store_true", help="kör bara de deterministiska vägarna")
    args = parser.parse_args(argv)

    project_dirs = sorted(p for p in args.projects_dir.iterdir() if (p / "expected").is_dir())
    if args.project:
        project_dirs = [p for p in project_dirs if p.name in set(args.project)]
    if not project_dirs:
        print("Inga facitprojekt hittades", file=sys.stderr)
        return 1

    sections, all_ok = [], True
    for project_dir in project_dirs:
        text, ok = evaluate_project(project_dir, args.require_inputs, use_ai=not args.no_ai)
        sections.append(text)
        all_ok &= ok

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    report = "\n".join([f"# VS-Kalkyl – utvärdering ({stamp})", "", *sections])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"Rapport: {args.report}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
