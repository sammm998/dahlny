"""Mängdlista ur en vvs_engine-körning: system × material × dimension, suffix som underrader (SPEC 6.4.7).

    python eval/tools/quantity_list.py KÖRNING TB.pdf [--skip-pages 4] [--deviations deviations.json]

KÖRNING är `vvs-takeoff analyze … --out KÖRNING`. Material som saknas fylls i ur systemets enda material i
projektet (TB + ritningens etiketter, app/tb/system_materials.py). Ett okänt suffix visas med avvikelsens id
ur facit (t.ex. A3-13), om en avvikelsefil anges. Sidnummer är 1-baserade; Bilaga A: --skip-pages 1,4.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config.settings import load_reference_tables  # noqa: E402
from app.drawings.quantities import QuantityRow, summarize  # noqa: E402
from app.drawings.vvs_engine import VvsEngineSource  # noqa: E402
from app.ingest.pdf_typed import open_pdf, page_text  # noqa: E402
from app.tb.system_materials import SystemMaterialIndex, from_designations, from_tb_pages  # noqa: E402


def _flag_text(flags: list[str], deviation_of: dict[str, str]) -> str:
    out = []
    for f in flags:
        _rule, _, token = f.partition(":")
        dev = deviation_of.get(token) if token else None
        out.append(f"{f} ({dev})" if dev else f)
    return ", ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("tb", type=Path)
    ap.add_argument(
        "--skip-pages", default="", help="1-baserade sidnummer som inte mängdas (t.ex. flödesschema)"
    )
    ap.add_argument("--deviations", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    takeoff = VvsEngineSource().read_artifacts(args.run)
    skip = {int(p) for p in args.skip_pages.split(",") if p}
    sheets = [s for s in takeoff.sheets if s.page not in skip]
    runs = [r for s in sheets for r in s.pipe_runs]
    with open_pdf(args.tb.read_bytes()) as tb:
        tb_pages = [(i + 1, page_text(tb[i])) for i in range(len(tb))]
    index = SystemMaterialIndex.build(
        from_tb_pages(tb_pages), from_designations((r.page, r.designation) for r in runs)
    )
    rt = load_reference_tables()
    known = {e.code for s in sheets for e in s.legend} | set(rt.materials) | set(rt.systems)
    rows: list[QuantityRow] = summarize(runs, known_codes=known, system_materials=index)
    deviation_of: dict[str, str] = {}
    if args.deviations:
        for d in json.loads(args.deviations.read_text(encoding="utf-8"))["deviations"]:
            if d["rule_id"] == "UNKNOWN_LABEL_TOKEN":
                for token in ("W40", "W", "F"):
                    if f" {token}" in d["description"] or f"{token}," in d["description"]:
                        deviation_of.setdefault(token, d["id"])
    print(f"{'Beteckning':<16} {'Material':<22} {'Meter':>8} {'Tvetydigt':>9}  Flaggor")
    totals: dict[str, float] = {}
    for row in rows:
        mat = row.material or "–"
        if row.material_source and row.material_source != "etikett":
            mat += f" ({row.material_source}, {row.material_confidence})"
        print(f"{row.base:<16} {mat:<22} {row.length_m:8.2f} {row.ambiguous_m:9.2f}  "
              f"{_flag_text(row.flags, deviation_of)}")  # fmt: skip
        for sub in row.sub_rows:
            label = f"  -{sub.suffix}" if sub.suffix else "  (utan suffix)"
            print(f"{label:<16} {'':<22} {sub.length_m:8.2f} {sub.ambiguous_m:9.2f}  "
                  f"{_flag_text(sub.flags, deviation_of)}")  # fmt: skip
        totals[row.system] = totals.get(row.system, 0.0) + row.length_m
    print("Summa per system: " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(totals.items()))
          + f"; totalt {sum(totals.values()):.2f} m")  # fmt: skip
    if args.json:
        args.json.write_text(json.dumps([r.model_dump() for r in rows], ensure_ascii=False, indent=1),
                             encoding="utf-8")  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
