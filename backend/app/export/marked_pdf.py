"""Markerad PDF (SPEC 6.4.6) och Excel-mängdlista.

Den markerade PDF:en är ritningen med varje mätt rör färgat per identitet (system × dimension), otilldelat
rött,
tvetydigt orange och "utanför entreprenadgräns" lila, och en första sida med summeringen. Markeringen ritas
som
vanligt sidinnehåll (inte som anteckningar), så att den syns likadant i Adobe och Bluebeam och följer med vid
utskrift. Ritningens egna sidor ändras inte i övrigt.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Sequence
from pathlib import Path

import pymupdf

from app.drawings.estimates import FittingEstimate, InsulationRow
from app.drawings.quantities import QuantityRow
from app.drawings.source import DrawingTakeoff
from app.ingest.pdf_typed import open_pdf, pdf_bytes

RED, ORANGE, PURPLE = (0.85, 0.05, 0.05), (1.0, 0.55, 0.0), (0.35, 0.2, 0.75)
# inga röda, orange eller lila toner: de betyder otilldelat, tvetydigt och utanför entreprenadgräns
PALETTE = [
    (0.05, 0.6, 0.1),
    (0.0, 0.35, 0.9),
    (0.0, 0.6, 0.6),
    (0.3, 0.3, 0.9),
    (0.6, 0.35, 0.1),
    (0.1, 0.45, 0.3),
    (0.5, 0.5, 0.0),
    (0.0, 0.2, 0.5),
    (0.35, 0.55, 0.0),
    (0.4, 0.25, 0.15),
]
STATE_COLOUR = {"UNOWNED": RED, "AMBIGUOUS": ORANGE, "OUTSIDE_CONTRACT": PURPLE}


def colour_key(system: str, dim: str | None) -> str:
    return f"{system.upper()}|{(dim or '').upper().removeprefix('DN')}"


def key_of_identity(identity: str) -> str:
    """Motorns identitet `KV01-K1-15|DN15` → samma nyckel som mängdraden (system och dimension)."""
    base, _, dn = identity.partition("|")
    return colour_key(base.split("-")[0], dn or None)


def identity_colour(key: str) -> tuple[float, float, float]:
    h = int(hashlib.sha256(key.encode()).hexdigest(), 16)
    return PALETTE[h % len(PALETTE)]


def _summary_page(
    doc: pymupdf.Document, rows: Sequence[QuantityRow], takeoff: DrawingTakeoff, title: str
) -> None:
    page = doc.new_page(0, width=842, height=595)  # A4 liggande, först i dokumentet
    y = 40.0
    page.insert_text(
        (40, y), f"Mängdning: {title}", fontsize=14, fontname="helv"
    )  # standardteckensnittet saknar tankstreck
    y += 22
    page.insert_text(
        (40, y), "Rörmeter per system × material × dimension (bekräftat, horisontellt)", fontsize=9
    )
    y += 16
    for r in rows:
        if y > 520:
            break
        page.draw_line((40, y - 3), (60, y - 3), color=identity_colour(colour_key(r.system, r.dim)), width=3)
        text = f"{r.system} {r.material or '–'} {r.dim or '–'}: {r.length_m:.2f} m"
        if r.ambiguous_m:
            text += f"  (tvetydigt {r.ambiguous_m:.2f} m)"
        page.insert_text((66, y), text, fontsize=8)
        y += 12
    y += 10
    for sh in takeoff.sheets:
        if sh.coverage is None or not sh.coverage.drawn_m or not sh.pipe_runs:
            continue  # bara mängdade blad (schemat och förteckningen mäts inte)
        c = sh.coverage
        page.insert_text(
            (40, y),
            f"Blad {sh.page}: ritat {c.drawn_m} m, otilldelat {c.unowned_m} m, tvetydigt "
            f"{c.ambiguous_m} m, utanför entreprenadgräns {c.outside_contract_m or 0} m",
            fontsize=8,
        )
        y += 12
    y += 8
    for colour, text in ((RED, "otilldelat"), (ORANGE, "tvetydigt"), (PURPLE, "utanför entreprenadgräns")):
        page.draw_line((40, y - 3), (60, y - 3), color=colour, width=3)
        page.insert_text((66, y), text, fontsize=8)
        y += 12


def marked_pdf(
    drawing_pdf: bytes, engine_dir: Path, takeoff: DrawingTakeoff, rows: Sequence[QuantityRow], title: str
) -> bytes:
    doc = open_pdf(drawing_pdf)
    for sh in takeoff.sheets:
        inv_path = engine_dir / "sheets" / str(sh.page - 1) / "pipe-geometry-inventory.json"
        if not inv_path.exists():
            continue
        prims = json.loads(inv_path.read_text(encoding="utf-8")).get("primitives", [])
        page = doc[sh.page - 1]
        shape = page.new_shape()  # type: ignore[no-untyped-call]
        for p in prims:
            state = p.get("state")
            colour = STATE_COLOUR.get(state) or identity_colour(key_of_identity(str(p.get("identity") or "")))
            shape.draw_line((p["x0"], p["y0"]), (p["x1"], p["y1"]))
            shape.finish(color=colour, width=2.2 if state in STATE_COLOUR else 1.6)
        shape.commit()
    _summary_page(doc, rows, takeoff, title)
    data = pdf_bytes(doc)
    doc.close()  # type: ignore[no-untyped-call]
    return data


def quantity_xlsx(
    rows: Sequence[QuantityRow],
    insulation: Sequence[InsulationRow],
    fittings: Sequence[FittingEstimate],
    outside: Sequence[object] = (),
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Rör"
    ws.append(
        [
            "System",
            "Material",
            "Materialkälla",
            "Dimension",
            "Meter (horisontellt)",
            "Tvetydigt m",
            "Blad",
            "Flaggor",
        ]
    )
    for r in rows:
        ws.append(
            [
                r.system,
                r.material or "",
                r.material_source or "",
                r.dim or "",
                round(r.length_m, 2),
                round(r.ambiguous_m, 2),
                ", ".join(map(str, r.pages)),
                ", ".join(r.flags),
            ]
        )
        for sub in r.sub_rows:
            ws.append(
                [
                    f"  -{sub.suffix}" if sub.suffix else "  (utan suffix)",
                    "",
                    "",
                    "",
                    round(sub.length_m, 2),
                    round(sub.ambiguous_m, 2),
                    "",
                    ", ".join(sub.flags),
                ]
            )
    for c in ws[1]:
        c.font = Font(bold=True)
    if outside:
        wo = wb.create_sheet("Utanför entreprenadgräns")
        wo.append(["Beteckning", "Meter", "Blad"])
        for o in outside:
            wo.append(
                [
                    getattr(o, "designation", None) or "–",
                    getattr(o, "length_m", None),
                    ", ".join(map(str, getattr(o, "pages", []))),
                ]
            )
    wi = wb.create_sheet("Isolering")
    wi.append(["System", "Dimension", "Meter", "TB-krav (ordagrant)", "Serie (ritningens matris)", "Flaggor"])
    for i in insulation:
        wi.append(
            [
                i.system,
                i.dim or "",
                round(i.length_m, 2),
                i.requirement or "",
                i.series or "",
                ", ".join(i.flags),
            ]
        )
    wf = wb.create_sheet("Rördelar (uppskattning)")
    wf.append(["Identitet", "Böjar", "Metod"])
    for f in fittings:
        wf.append([f.identity, f.bends, f.method])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
