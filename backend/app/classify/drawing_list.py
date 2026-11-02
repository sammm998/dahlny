"""Tolkning av ritningsförteckningen ur textlagret (SPEC 6.1.6).

Kolumnerna hittas via rubrikraden (ordförrådet i documents.yaml) och varje ord förs till den kolumn vars
rubrik börjar närmast till vänster om ordet. Rader med ritningsnummer är ritningar; rader utan ritningsnummer
men med datum är andra handlingar (t.ex. teknisk beskrivning); övriga rader är rubriker.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

from app.classify.patterns import (
    ScaleRatio,
    dates,
    drawing_numbers,
    is_no_scale,
    project_number,
    scale_ratios,
)
from app.config.settings import load_documents_config
from app.ingest.pdf_typed import page_text, page_words


@dataclass(frozen=True)
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class DrawingListEntry:
    kind: str  # "drawing" | "document" | "heading"
    drawing_no: str | None
    title: str
    revision: str | None
    status: str | None
    scale_text: str | None
    scales: tuple[ScaleRatio, ...]
    no_scale: bool
    date: str | None
    changed: str | None
    bbox: tuple[float, float, float, float]


@dataclass
class DrawingList:
    page_no: int
    project_no: str | None
    entries: list[DrawingListEntry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def drawings(self) -> list[DrawingListEntry]:
        return [e for e in self.entries if e.kind == "drawing"]


def words_of(page: pymupdf.Page) -> list[Word]:
    return [Word(*w) for w in page_words(page)]


def group_rows(words: list[Word], tolerance_fraction: float) -> list[list[Word]]:
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.yc, w.x0)):
        if rows:
            last = rows[-1]
            ref = sum(x.yc for x in last) / len(last)
            if abs(w.yc - ref) <= tolerance_fraction * max(w.height, last[0].height):
                last.append(w)
                continue
        rows.append([w])
    return [sorted(r, key=lambda w: w.x0) for r in rows]


def _find_header(
    rows: list[list[Word]], columns: dict[str, list[str]]
) -> tuple[int, dict[str, float]] | None:
    for i, row in enumerate(rows):
        tokens = [w.text.upper() for w in row]
        starts: dict[str, float] = {}
        for col, names in columns.items():
            for name in sorted(names, key=lambda n: -len(n.split())):  # flerordsrubriker först
                parts = name.split()
                for j in range(len(tokens) - len(parts) + 1):
                    if tokens[j : j + len(parts)] == parts and col not in starts:
                        starts[col] = row[j].x0
        if "drawing_no" in starts and "title" in starts:
            return i, starts
    return None


def parse_drawing_list(page: pymupdf.Page) -> DrawingList:
    cfg = load_documents_config().drawing_list
    rows = group_rows(words_of(page), cfg.row_tolerance_fraction)
    result = DrawingList(page_no=page.number + 1, project_no=project_number(str(page_text(page, "text"))))
    header = _find_header(rows, cfg.columns)
    if header is None:
        result.problems.append("Hittade ingen rubrikrad (RITNINGSNUMMER … INNEHÅLL) i förteckningen")
        return result
    header_index, starts = header
    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    slack = 2.0  # pt – ord som börjar strax före rubriken hör till den

    gaps: list[float] = []
    previous_y = sum(w.yc for w in rows[header_index]) / len(rows[header_index])
    for row in rows[header_index + 1 :]:
        y = sum(w.yc for w in row) / len(row)
        if gaps and y - previous_y > cfg.table_end_gap_factor * sorted(gaps)[len(gaps) // 2]:
            break  # stort hopp nedåt: tabellen är slut, resten är sidfot/stämpel
        gaps.append(y - previous_y)
        previous_y = y
        cells: dict[str, list[str]] = {}
        for w in row:
            col = None
            for name, x in ordered:
                if w.x0 + slack >= x:
                    col = name
            if col is not None:
                cells.setdefault(col, []).append(w.text)
        text = {k: " ".join(v) for k, v in cells.items()}
        numbers = drawing_numbers(text.get("drawing_no", ""))
        title = text.get("title", "").strip()
        scale_text = text.get("scale")
        date_values = dates(text.get("date", ""))
        changed_values = dates(text.get("changed", ""))
        if not title and not numbers:
            continue  # sidfot, adress och liknande utanför tabellen
        kind = "drawing" if numbers else ("document" if date_values else "heading")
        if text.get("drawing_no") and not numbers:
            result.problems.append(f"Okänt ritningsnummerformat: {text['drawing_no']!r}")
        result.entries.append(
            DrawingListEntry(
                kind=kind,
                drawing_no=numbers[0] if numbers else None,
                title=title,
                revision=text.get("revision"),
                status=text.get("status"),
                scale_text=scale_text,
                scales=tuple(scale_ratios(scale_text or "")),
                no_scale=bool(scale_text) and is_no_scale(scale_text or ""),
                date=date_values[0] if date_values else None,
                changed=changed_values[0] if changed_values else None,
                bbox=(
                    min(w.x0 for w in row),
                    min(w.y0 for w in row),
                    max(w.x1 for w in row),
                    max(w.y1 for w in row),
                ),
            )
        )
    return result
