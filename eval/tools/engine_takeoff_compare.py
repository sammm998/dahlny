"""vvs_engine före och efter T5-etiketterna: otilldelad rörlängd, bekräftade meter, tvetydiga rör (per blad).

    python eval/tools/engine_takeoff_compare.py FÖRE_KATALOG EFTER_KATALOG [--sheets 1,2,3] [--json UT.json]

Katalogerna är `vvs-takeoff analyze … --out KATALOG` utan respektive med `--labels`. Per blad läses
`coverage-validity.json` (andel bläck som är bekräftat, tvetydigt, otilldelat), `quantities.json` (meter per
beteckning) och `pipe-geometry-inventory.json` (varje rörbits status, kandidater och skäl). Material tas ur
bladets egen beteckningslista (`drawing-legend.json`, roll `material`) – en kod i beteckningen som listan
säger är ett material. Bekräftade meter = `confirmed_total_m - review_m` (granskningsnivån räknas för sig).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _materials(legend: dict[str, Any] | None) -> dict[str, str]:
    out = {}
    for e in (legend or {}).get("entries", []):
        if e.get("role") == "material" and e.get("code"):
            out[str(e["code"]).upper()] = str(e.get("description") or "")
    return out


def _material_of(designation: str, materials: dict[str, str]) -> str:
    for tok in designation.upper().replace(" ", "-").split("-"):
        if tok in materials:
            return f"{tok} ({materials[tok]})"
    return "–"


def sheet(run: Path, sheet_no: int) -> dict[str, Any]:
    d = run / "sheets" / str(sheet_no)
    cov = (_load(d / "coverage-validity.json") or {}).get("measures", {})
    q = _load(d / "quantities.json") or {}
    mpp = ((q.get("scale") or {}).get("meters_per_pdf_point")) or 0.0
    materials = _materials(_load(d / "drawing-legend.json"))
    rows = []
    for r in q.get("rows", []):
        confirmed = float(r.get("confirmed_total_m") or 0) - float(r.get("review_m") or 0)
        rows.append(
            {
                "designation": r.get("designation"),
                "system": r.get("system") or r.get("base"),
                "material": _material_of(str(r.get("designation") or ""), materials),
                "dn": r.get("dn"),
                "confirmed_m": round(confirmed, 2),
                "review_m": round(float(r.get("review_m") or 0), 2),
                "ambiguous_m": round(float(r.get("ambiguous_m") or 0), 2),
                "state": r.get("state"),
            }
        )
    inv = (_load(d / "pipe-geometry-inventory.json") or {}).get("primitives", [])
    length: dict[str, float] = defaultdict(float)
    groups: dict[tuple[str, tuple[str, ...]], float] = defaultdict(float)
    for p in inv:
        length[p.get("state") or "?"] += float(p.get("length") or 0)
        if p.get("state") == "AMBIGUOUS":
            groups[(p.get("reason") or "?", tuple(sorted(p.get("candidates") or [])))] += float(
                p.get("length") or 0
            )
    ext = _load(d / "external-labels.json")
    return {
        "scale_m_per_pt": mpp,
        "scale_state": (q.get("scale") or {}).get("state"),
        "unowned_share": cov.get("INK_UNOWNED_SHARE"),
        "ambiguous_share": cov.get("INK_AMBIGUOUS_SHARE"),
        "confirmed_share": cov.get("INK_CONFIRMED_SHARE"),
        "length_m_by_state": {k: round(v * mpp, 2) for k, v in sorted(length.items())},
        "rows": rows,
        "ambiguous": [
            {"reason": k[0], "candidates": list(k[1]), "m": round(v * mpp, 2)}
            for k, v in sorted(groups.items(), key=lambda kv: -kv[1])
        ],
        "external_labels": {k: ext.get(k) for k in ("labels", "changed", "added", "unchanged", "uncertain")}
        if ext
        else None,
    }


def by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str, Any], float]:
    out: dict[tuple[str, str, Any], float] = defaultdict(float)
    for r in rows:
        if r["confirmed_m"] > 0:
            out[(str(r["system"]), r["material"], r["dn"])] += r["confirmed_m"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--sheets", default="1,2,3")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    result: dict[str, Any] = {}
    for s in [int(x) for x in args.sheets.split(",")]:
        b, a = sheet(args.before, s), sheet(args.after, s)
        result[str(s)] = {"before": b, "after": a}
        print(f"## Blad {s} (sidindex {s}), skala {a['scale_state']} {a['scale_m_per_pt']:.6f} m/pt")
        for label, k in (
            ("otilldelad", "unowned_share"),
            ("tvetydig", "ambiguous_share"),
            ("bekräftad", "confirmed_share"),
        ):
            print(f"   andel {label}: före {b[k]}  efter {a[k]}")
        if a["external_labels"]:
            print(f"   etikettfilen: {a['external_labels']}")
        kb, ka = by_key(b["rows"]), by_key(a["rows"])
        print("   bekräftade meter (system × material × DN): före → efter")
        for key in sorted(set(kb) | set(ka), key=lambda t: (t[0], t[1], t[2] or 0)):
            dn = f"DN{key[2]!s:<5}"
            print(f"      {key[0]:<10} {key[1]:<28} {dn} {kb.get(key, 0):7.2f} → {ka.get(key, 0):7.2f}")
        print(
            f"   summa: {sum(kb.values()):.2f} → {sum(ka.values()):.2f} m; granska (review): "
            f"{sum(r['review_m'] for r in b['rows']):.2f} → {sum(r['review_m'] for r in a['rows']):.2f} m"
        )
        print("   tvetydigt efter:")
        for g in a["ambiguous"]:
            print(f"      {g['m']:6.2f} m  {g['reason']}: {', '.join(g['candidates'])}")
    if args.json:
        args.json.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
