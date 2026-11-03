"""TB-layout: rader med kolumnerna KOD / TEXT / MÄNGD / ENHET (SPEC 6.2 steg 1–2).

Kolumnernas x-gränser tas ur sidhuvudets kolumnrubriker (`KOD`, `TEXT`, `MÄNGD`, `ENHET`). Allt ovanför
rubrikraden är sidhuvud och tas bort; rader som återkommer på samma plats på de flesta sidor (sidfot) tas
också
bort. En sida utan kolumnrubriker ärver föregående sidas gränser. Varje rad bär sin källa (sida, bbox) och om
texten är fetstil eller kursiv – segmenteringen använder fetstil för objektbeteckningar.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from app.ingest.pdf_typed import page_text

HEADER_WORDS = ("KOD", "TEXT", "MÄNGD", "ENHET")
LINE_TOL_PT = 2.5  # spann vars överkanter ligger så nära är samma rad
BOLD_FLAG = 16
ITALIC_FLAG = 2
REPEAT_SHARE = 0.6  # en rad på samma plats på så stor andel av sidorna är sidfot/sidhuvud


@dataclass(frozen=True)
class Columns:
    kod_x: float
    text_x: float
    mangd_x: float
    enhet_x: float
    header_bottom: float  # y under rubrikraden – allt ovanför är sidhuvud

    def column_of(self, x: float) -> str:
        if x < self.text_x - 4:
            return "kod"
        if x < self.mangd_x - 40:
            return "text"
        return "mangd"


@dataclass
class Span:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    bold: bool
    italic: bool


@dataclass
class TBLine:
    page: int  # 1-baserad
    y: float
    kod: str
    text: str
    mangd: str
    bbox: tuple[float, float, float, float]
    bold_text: bool  # hela TEXT-kolumnen i fetstil
    italic_text: bool
    spans: list[Span] = field(default_factory=list)

    @property
    def all_text(self) -> str:
        return " ".join(p for p in (self.kod, self.text, self.mangd) if p)


def _spans(page: pymupdf.Page) -> list[Span]:
    out: list[Span] = []
    for block in page_text(page, "dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                text = s["text"].strip()
                if not text:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                flags = int(s["flags"])
                font = str(s.get("font", ""))
                out.append(
                    Span(
                        x0,
                        y0,
                        x1,
                        y1,
                        text,
                        bool(flags & BOLD_FLAG) or "Bold" in font,
                        bool(flags & ITALIC_FLAG) or "Italic" in font,
                    )
                )
    return out


def find_columns(spans: list[Span]) -> Columns | None:
    """Kolumnrubrikerna på en rad: KOD, TEXT, MÄNGD, ENHET i den ordningen från vänster."""
    by_word: dict[str, list[Span]] = {w: [s for s in spans if s.text.upper() == w] for w in HEADER_WORDS}
    for kod in by_word["KOD"]:
        row = {
            w: next((s for s in by_word[w] if abs(s.y0 - kod.y0) <= LINE_TOL_PT), None) for w in HEADER_WORDS
        }
        if all(row.values()):
            k, t, m, e = (row[w] for w in HEADER_WORDS)
            assert k and t and m and e
            if k.x0 < t.x0 < m.x0 < e.x0:
                return Columns(k.x0, t.x0, m.x0, e.x0, max(s.y1 for s in (k, t, m, e)))
    return None


def _group_lines(spans: list[Span]) -> list[list[Span]]:
    lines: list[list[Span]] = []
    for s in sorted(spans, key=lambda s: (round(s.y0, 1), s.x0)):
        if lines and abs(lines[-1][0].y0 - s.y0) <= LINE_TOL_PT:
            lines[-1].append(s)
        else:
            lines.append([s])
    return [sorted(line, key=lambda s: s.x0) for line in lines]


def _norm_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def read_layout(doc: pymupdf.Document) -> list[TBLine]:
    """Alla brödtextrader i dokumentet, utan sidhuvud och sidfot, med kolumnerna separerade."""
    pages: list[tuple[int, list[list[Span]], Columns | None]] = []
    cols: Columns | None = None
    for i in range(len(doc)):
        spans = _spans(doc[i])
        found = find_columns(spans)
        cols = found or cols
        body = [s for s in spans if cols is None or s.y0 > cols.header_bottom] if found or cols else spans
        pages.append((i + 1, _group_lines(body), cols))
    # sidfot: samma text (siffror utjämnade) på ungefär samma höjd på de flesta sidor
    seen: Counter[tuple[str, int]] = Counter()
    for _, lines, _ in pages:
        keys = {(_norm_key(" ".join(s.text for s in ln)), int(ln[0].y0 // 10)) for ln in lines}
        seen.update(keys)
    repeated = {k for k, n in seen.items() if len(pages) > 2 and n >= REPEAT_SHARE * len(pages)}
    out: list[TBLine] = []
    for page_no, lines, c in pages:
        for ln in lines:
            if (_norm_key(" ".join(s.text for s in ln)), int(ln[0].y0 // 10)) in repeated:
                continue
            parts: dict[str, list[Span]] = {"kod": [], "text": [], "mangd": []}
            for s in ln:
                parts[c.column_of(s.x0) if c else "text"].append(s)
            text_spans = parts["text"]
            out.append(
                TBLine(
                    page=page_no,
                    y=ln[0].y0,
                    kod=" ".join(s.text for s in parts["kod"]),
                    text=" ".join(s.text for s in text_spans),
                    mangd=" ".join(s.text for s in parts["mangd"]),
                    bbox=(
                        min(s.x0 for s in ln),
                        min(s.y0 for s in ln),
                        max(s.x1 for s in ln),
                        max(s.y1 for s in ln),
                    ),
                    bold_text=bool(text_spans) and all(s.bold for s in text_spans),
                    italic_text=bool(text_spans) and all(s.italic for s in text_spans),
                    spans=ln,
                )
            )
    return out
