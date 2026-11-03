"""Var den otilldelade rörlängden ligger, per blad: markerad PDF, bild och grupperade orsaker.

    python eval/tools/unassigned_map.py KÖRNING RITNINGAR.pdf UT_KATALOG [--sheets 1,2] [--near-pt 80]

KÖRNING är `vvs-takeoff analyze … --out KÖRNING`. Per blad (motorns 0-baserade sidindex):
- `pipe-geometry-inventory.json`: varje rörbit med status (CONFIRMED / AMBIGUOUS / UNOWNED) och koordinater;
- `unresolved-issues.json`: rörbeteckningar som inte fäste (ingen ledare, eller ledaren når inget rör);
- `quantities.json` `outside_contract`: sträckor bortom en entreprenadgräns (status OUTSIDE_CONTRACT).
  De ritas lila med gränspunkten som ett kryss och räknas för sig – varken otilldelat eller bekräftat.
Otilldelade bitar i samma lager som möts (`--join-pt`) blir en sträcka. Varje sträcka får en orsaksgrupp:
  A  fortsättning på ett namngivet rör som ingen etikett når (sträckan rör vid namngiven geometri);
  B  fristående, och en rörbeteckning i närheten (`--near-pt`) saknar ledare;
  C  fristående, och en rörbeteckning i närheten har en ledare som inte når något rör;
  D  fristående, ingen rörbeteckning i närheten.
Gruppen är en karta för granskning, inte en diagnos: den säger vad som ligger nära, inte varför motorn
gjorde så.
Utdata: UT/blad_<n>.pdf (bladet med markeringar, beskuret till rören), UT/blad_<n>.png, UT/otilldelat.json.
Ritningarna är kundmaterial – utdata checkas inte in.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import pymupdf

TOUCH_PT = 1.5  # ändpunkt så här nära namngiven geometri = sträckan hänger på röret
RED, ORANGE, GREEN, BLUE = (0.85, 0.05, 0.05), (1.0, 0.55, 0.0), (0.1, 0.6, 0.2), (0.1, 0.3, 0.95)
PURPLE = (0.35, 0.2, 0.75)
OUTSIDE = "OUTSIDE_CONTRACT"
OUTSIDE_LABEL = "utanför entreprenadgräns"
GROUPS = {
    "A": "fortsättning på namngivet rör som ingen etikett når",
    "B": "fristående – närliggande rörbeteckning saknar ledare",
    "C": "fristående – närliggande rörbeteckning har ledare som inte når något rör",
    "D": "fristående – ingen rörbeteckning i närheten",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _ends(p: dict[str, Any]) -> list[tuple[float, float]]:
    return [(p["x0"], p["y0"]), (p["x1"], p["y1"])]


def _near(a: tuple[float, float], b: tuple[float, float], d: float) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= d


def _box_dist(pt: tuple[float, float], box: list[float]) -> float:
    dx = max(box[0] - pt[0], 0.0, pt[0] - box[2])
    dy = max(box[1] - pt[1], 0.0, pt[1] - box[3])
    return math.hypot(dx, dy)


def components(prims: list[dict[str, Any]], join: float) -> list[list[dict[str, Any]]]:
    parent = list(range(len(prims)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(prims):
        for j in range(i + 1, len(prims)):
            b = prims[j]
            if a["family"] == b["family"] and any(_near(p, q, join) for p in _ends(a) for q in _ends(b)):
                parent[find(i)] = find(j)
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, p in enumerate(prims):
        groups[find(i)].append(p)
    return list(groups.values())


def sheet_map(
    run: Path, doc: pymupdf.Document, sheet: int, out: Path, near: float, join: float
) -> dict[str, Any]:
    d = run / "sheets" / str(sheet)
    inv = (_load(d / "pipe-geometry-inventory.json") or {}).get("primitives", [])
    quantities = _load(d / "quantities.json") or {}
    mpp = (quantities.get("scale") or {}).get("meters_per_pdf_point") or 0.0
    outside = quantities.get("outside_contract") or []
    issues = (_load(d / "unresolved-issues.json") or {}).get("issues", [])
    unplaced = [i for i in issues if i["kind"] in ("missing_leader", "missing_pipe_attachment")]
    named_ends = [e for p in inv if p["state"] in ("CONFIRMED", "AMBIGUOUS") for e in _ends(p)]
    runs = []
    for comp in components([p for p in inv if p["state"] == "UNOWNED"], join):
        ends = [e for p in comp for e in _ends(p)]
        xs, ys = [e[0] for e in ends], [e[1] for e in ends]
        box = [min(xs), min(ys), max(xs), max(ys)]
        centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        touches = any(_near(e, n, TOUCH_PT) for e in ends for n in named_ends)
        nearby = sorted(
            ((min(_box_dist(e, i["bbox"]) for e in ends), i) for i in unplaced), key=lambda t: t[0]
        )
        nearby = [(dist, i) for dist, i in nearby if dist <= near]
        if touches:
            group = "A"
        elif any(i["kind"] == "missing_leader" for _, i in nearby):
            group = "B"
        elif nearby:
            group = "C"
        else:
            group = "D"
        runs.append({
            "length_m": round(sum(p["length"] for p in comp) * mpp, 2), "family": comp[0]["family"],
            "layer": comp[0]["family"].split("|s|")[0], "bbox": [round(v, 1) for v in box],
            "centre": [round(v, 1) for v in centre], "group": group, "touches_named_pipe": touches,
            "nearby_labels": [{"text": i["text"], "kind": i["kind"], "reason": i.get("reason"),
                               "distance_pt": round(dist, 1)} for dist, i in nearby[:3]],
        })  # fmt: skip
    runs.sort(key=lambda r: -r["length_m"])
    for n, r in enumerate(runs, 1):
        r["no"] = n
    page = doc[sheet]
    shape = page.new_shape()
    for p in inv:
        colour = {"UNOWNED": RED, "AMBIGUOUS": ORANGE, OUTSIDE: PURPLE}.get(p["state"], GREEN)
        width = {"UNOWNED": 2.4, "AMBIGUOUS": 1.8, OUTSIDE: 2.4}.get(p["state"], 1.0)
        shape.draw_line((p["x0"], p["y0"]), (p["x1"], p["y1"]))
        shape.finish(color=colour, width=width)
    for o in outside:  # sträckan bortom gränsen (också den kapade bitens yttre del) och gränspunkten
        for (ax, ay), (bx, by) in o.get("geometry") or []:
            shape.draw_line((ax, ay), (bx, by))
            shape.finish(color=PURPLE, width=2.4)
        x, y = o["boundary_point"]
        shape.draw_line((x - 4, y - 4), (x + 4, y + 4))
        shape.draw_line((x - 4, y + 4), (x + 4, y - 4))
        shape.finish(color=PURPLE, width=1.4)
    for i in unplaced:
        x0, y0, x1, y1 = i["bbox"]
        shape.draw_rect(pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2))
        shape.finish(color=BLUE, width=1.2)
    shape.commit()
    for r in runs:
        page.insert_text((r["bbox"][2] + 3, r["bbox"][1] + 2), str(r["no"]), fontsize=9, color=RED)
    pts = [e for p in inv for e in _ends(p)] + [(i["bbox"][0], i["bbox"][1]) for i in unplaced]
    clip = pymupdf.Rect(min(x for x, _ in pts) - 40, min(y for _, y in pts) - 40,
                        max(x for x, _ in pts) + 40, max(y for _, y in pts) + 40) & page.rect  # fmt: skip
    one = pymupdf.open()
    one.insert_pdf(doc, from_page=sheet, to_page=sheet)
    one[0].set_cropbox(clip)
    one.save(out / f"blad_{sheet}.pdf")
    zoom = min(3.0, 2400 / max(clip.width, 1.0))
    page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip).save(out / f"blad_{sheet}.png")
    totals = {k: round(sum(r["length_m"] for r in runs if r["group"] == k), 2) for k in GROUPS}
    beyond = [{"designation": o.get("designation"), "length_m": o.get("length_m"),
               "boundary_point": o.get("boundary_point")} for o in outside]  # fmt: skip
    return {"sheet": sheet, "unowned_m": round(sum(r["length_m"] for r in runs), 2), "by_group_m": totals,
            "outside_contract_m": round(sum(o["length_m"] or 0.0 for o in beyond), 2),
            "outside_contract": beyond,
            "runs": runs, "unplaced_labels": [{k: i.get(k) for k in ("text", "kind", "reason", "bbox")}
                                              for i in unplaced]}  # fmt: skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--sheets", default="1,2")
    ap.add_argument(
        "--near-pt", type=float, default=80.0, help="avstånd till en rörbeteckning som räknas som nära"
    )
    ap.add_argument(
        "--join-pt",
        type=float,
        default=8.0,
        help="ändpunkter så här nära (samma lager) hör till samma sträcka – täcker streckade linjers pauser",
    )
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(args.pdf)
    result = [
        sheet_map(args.run, doc, int(s), args.out, args.near_pt, args.join_pt) for s in args.sheets.split(",")
    ]
    for res in result:
        print(f"## Blad {res['sheet']}: {res['unowned_m']} m otilldelat")
        for k, label in GROUPS.items():
            print(f"   {k} {res['by_group_m'][k]:6.2f} m  {label}")
        print(f"   {res['outside_contract_m']:8.2f} m  {OUTSIDE_LABEL} (egen kategori, inte otilldelat)")
        for o in res["outside_contract"]:
            print(f"        {o['designation'] or '–'}: {o['length_m']} m, gräns vid {o['boundary_point']}")
        for r in res["runs"]:
            near = (
                "; ".join(f"{n['text']} ({n['kind']}, {n['distance_pt']} pt)" for n in r["nearby_labels"])
                or "–"
            )
            head = f"   #{r['no']:<3} {r['group']} {r['length_m']:6.2f} m  {r['layer']:<16}"
            print(f"{head} vid {r['centre']}  "
                  f"nära: {near}")  # fmt: skip
    (args.out / "otilldelat.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
