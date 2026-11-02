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
        ("Avvikelser", f"{len(facit.deviations.deviations)} (A.3 nr 1–11, nr 10 i två delar)"),
        ("Etiketter", f"{len(labels)} på {len(facit.labels.drawings)} ritningar ({unknown} med okänd token)"),
        (
            "Symbolantal",
            f"{len(facit.symbols.counts)} grupper, {len(facit.symbols.legend_tables)} legendtabeller",
        ),
    ]


def evaluate_project(project_dir: Path, require_inputs: bool) -> tuple[str, bool]:
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

    lines += ["### Mått (SPEC 11.2)", "", "| Mått | Gräns | Resultat |", "| --- | --- | --- |"]
    lines += [f"| {m.name} | {m.limit} | ej mätt (fas {m.phase}) |" for m in METRICS]
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
    args = parser.parse_args(argv)

    project_dirs = sorted(p for p in args.projects_dir.iterdir() if (p / "expected").is_dir())
    if args.project:
        project_dirs = [p for p in project_dirs if p.name in set(args.project)]
    if not project_dirs:
        print("Inga facitprojekt hittades", file=sys.stderr)
        return 1

    sections, all_ok = [], True
    for project_dir in project_dirs:
        text, ok = evaluate_project(project_dir, args.require_inputs)
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
