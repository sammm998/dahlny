"""Legendtabeller på ritningen (FÖRKLARINGAR, MATRIS FÖR ISOLERING) – vision T2L med kontroll mot T5 (SPEC
6.4, A.5).

Rubriken hittas bland T5-läsningarna; utsnittet går från rubriken nedåt till nästa kända rubrik (högst
TABLE_MAX_HEIGHT_PT) och renderas i 200 dpi. Varje cell som T2L läser ska också finnas bland T5:s läsningar
inom
utsnittet (samma text efter att blanksteg tagits bort); annars flaggas cellen – den används inte tyst.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.ai.client import AIClient, AIError
from app.ai.datatypes import ContentPart, ImagePart, TextPart
from app.ingest.pdf_typed import open_pdf, png_bytes, rect

HEADINGS = ("FÖRKLARINGAR", "MATRIS FÖR ISOLERING")
TABLE_MAX_HEIGHT_PT = 220.0
TABLE_WIDTH_PT = 380.0
TABLE_LEFT_MARGIN_PT = 90.0  # en tabell kan börja till vänster om sin centrerade rubrik
RENDER_DPI = 200


class TableReading(BaseModel):
    title: str
    columns: list[str]
    rows: list[list[str | None]]
    notes: list[str] = Field(default_factory=list)


@dataclass
class LegendTable:
    page: int
    title: str
    columns: list[str]
    rows: list[list[str | None]]
    notes: list[str]
    bbox: tuple[float, float, float, float]
    unconfirmed_cells: list[str] = field(default_factory=list)


def _norm(t: str) -> str:
    return "".join(t.upper().split())


def read_tables(
    pdf_bytes: bytes, labels: dict[str, Any], ai: AIClient, project_id: uuid.UUID | None = None
) -> list[LegendTable]:
    """labels: T5-filen ({sidindex: {"rows": [...]}}, 0-baserat sidindex)."""
    out: list[LegendTable] = []
    with open_pdf(pdf_bytes) as doc:
        for key, sheet in labels.items():
            if key.startswith("_"):
                continue
            rows = sheet.get("rows", [])
            heads = [r for r in rows if _norm(r["text"]) in {_norm(h) for h in HEADINGS}]
            for h in heads:
                x0, y0 = h["bbox"][0] - TABLE_LEFT_MARGIN_PT, h["bbox"][1] - 4
                below = [r["bbox"][1] for r in heads if r["bbox"][1] > h["bbox"][3] + 5]
                y1 = min([y0 + TABLE_MAX_HEIGHT_PT, *[b - 4 for b in below]])
                box = (x0, y0, x0 + TABLE_WIDTH_PT, y1)
                page = doc[int(key)]
                pix = page.get_pixmap(dpi=RENDER_DPI, clip=rect(box))
                parts: list[ContentPart] = [
                    TextPart(f"Tabellens rubrik: {h['text']}"),
                    ImagePart(png_bytes(pix), "image/png", f"legend_{key}"),
                ]
                try:
                    t = ai.structured("T2L", parts, TableReading, project_id=project_id)
                except AIError:
                    continue
                seen = {
                    _norm(r["text"])
                    for r in rows
                    if r["bbox"][0] >= box[0] - 2
                    and r["bbox"][2] <= box[2] + 2
                    and r["bbox"][1] >= box[1] - 2
                    and r["bbox"][3] <= box[3] + 2
                }
                words = {w for s in seen for w in s.split(",")} | seen
                unconfirmed = [
                    c
                    for row in t.rows
                    for c in row
                    if c and c != "?" and _norm(c) not in words and not any(_norm(c) in s for s in seen)
                ]
                out.append(LegendTable(int(key) + 1, t.title, t.columns, t.rows, t.notes, box, unconfirmed))
    return out
