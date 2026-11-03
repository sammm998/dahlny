"""Deterministisk segmentering av TB (SPEC 6.2 steg 3).

En **sektion** börjar vid en AMA-kod i KOD-kolumnen (`PRB.12`, `PNU.311`) och bär rubrikkedjan. Ett
**segment**
börjar vid en objektbeteckning: fetstil i TEXT-kolumnen som matchar stilprofilens beteckningsregex
(standard `^[A-Z]{1,4}[0-9]{2,4}[A-Z]?$`), en rörbeteckning enligt `label_grammar.yaml`, eller ett fritt ord i
versaler med mängd på samma rad (`TRYCKLUFTSUTTAG  4 st`). En AMA-kod med mängd på sin egen rad eller närmast
under (`PAK.514 … 2st`) är också ett segment. Mängden tas ur MÄNGD-kolumnen på samma rad (eller de närmaste
raderna
inom segmentets början) och tolkas deterministiskt (`quantity.parse_quantity`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config.settings import load_label_grammar
from app.tb.layout import TBLine
from app.tb.quantity import ParsedQuantity, parse_quantity

AMA_CODE_RE = re.compile(r"^([A-Z]{1,4}(?:\.[0-9]{1,5})?)(?:\s+(.*))?$")
DESIGNATION_RE = re.compile(r"^[A-Z]{1,4}[0-9]{2,4}[A-Z]?$")
FREE_WORD_RE = re.compile(r"^[A-ZÅÄÖ]{5,}$")
QTY_LOOKAHEAD_LINES = 3  # en AMA-kod är ett eget objekt bara om mängden står så nära koden


@dataclass
class Section:
    code: str
    title: str
    chain: list[tuple[str, str]]  # rubrikkedjan från toppnivå, (kod, rubrik)
    lines: list[TBLine] = field(default_factory=list)

    @property
    def page(self) -> int:
        return self.lines[0].page if self.lines else 0


@dataclass
class Segment:
    sid: str
    designation: str
    kind: str  # object | pipe | ama_item
    section: Section
    lines: list[TBLine]
    quantity_text: str | None
    quantity: ParsedQuantity | None

    @property
    def text(self) -> str:
        return "\n".join(ln.all_text for ln in self.lines)

    @property
    def pages(self) -> list[int]:
        return sorted({ln.page for ln in self.lines})


def _is_code(kod: str) -> re.Match[str] | None:
    return AMA_CODE_RE.match(kod.strip()) if kod.strip() else None


def _level(code: str) -> int:
    head, _, tail = code.partition(".")
    return len(head) + len(tail)


def _pipe_patterns() -> list[re.Pattern[str]]:
    return [re.compile(p) for p in load_label_grammar().all_patterns()]


def _first_bold_word(line: TBLine) -> tuple[str, bool] | None:
    """Första ordet i TEXT-kolumnen om det står i fetstil, och om raden bara är det ordet
    (`VVB001 Fabrikat Nibe …` på samma rad räknas – beteckningen står först)."""
    text_spans = [s for s in line.spans if s.text and s.text in line.text]
    if not text_spans or not text_spans[0].bold:
        return None
    words = line.text.strip().split()
    return (words[0], len(words) == 1) if words else None


def _designation_kind(line: TBLine, pipes: list[re.Pattern[str]]) -> tuple[str, str] | None:
    first = _first_bold_word(line)
    if not first:
        return None
    word, alone = first
    if DESIGNATION_RE.match(word):
        return word, "object"
    if alone and "-" in word and any(p.fullmatch(word) for p in pipes):
        return word, "pipe"
    if alone and FREE_WORD_RE.match(word) and line.mangd.strip():
        return word, "object"
    return None


def sections(lines: list[TBLine]) -> list[Section]:
    out: list[Section] = []
    chain: list[tuple[str, str]] = []
    current: Section | None = None
    for ln in lines:
        m = _is_code(ln.kod)
        if m:
            code = m.group(1)
            title = (m.group(2) or ln.text or "").strip()
            chain = [c for c in chain if _level(c[0]) < _level(code) and code.startswith(c[0])]
            chain.append((code, title))
            current = Section(code, title, list(chain), [ln])
            out.append(current)
            continue
        if current is None:
            current = Section("", "", [], [])
            out.append(current)
        current.lines.append(ln)
    return out


def segments(secs: list[Section]) -> list[Segment]:
    pipes = _pipe_patterns()
    out: list[Segment] = []
    n = 0
    for sec in secs:
        starts: list[tuple[int, str, str]] = []
        for i, ln in enumerate(sec.lines):
            found = None if i == 0 else _designation_kind(ln, pipes)
            if found:
                starts.append((i, found[0], found[1]))
        # en AMA-kod vars egen rad, eller raderna närmast under innan nästa beteckning, bär en mängd
        if not starts:
            head = sec.lines[: QTY_LOOKAHEAD_LINES + 2]
            if any(parse_quantity(ln.mangd) for ln in head if ln.mangd.strip()):
                starts.append((0, sec.code, "ama_item"))
        for k, (i, designation, kind) in enumerate(starts):
            end = starts[k + 1][0] if k + 1 < len(starts) else len(sec.lines)
            seg_lines = sec.lines[i:end]
            # första tolkningsbara mängden i segmentet (MÄNGD-kolumnen kan också bära t.ex. "Ansl. nr. 25")
            qty_text = next((ln.mangd.strip() for ln in seg_lines if parse_quantity(ln.mangd)), None)
            n += 1
            out.append(
                Segment(
                    sid=f"s{n}",
                    designation=designation,
                    kind=kind,
                    section=sec,
                    lines=seg_lines,
                    quantity_text=qty_text,
                    quantity=parse_quantity(qty_text) if qty_text else None,
                )
            )
    return out
