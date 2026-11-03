"""Mängdtext ur TB:ns MÄNGD-kolumn → antal och quantity_mode (SPEC 6.2 steg 4, deterministiskt)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

PER_DRAWING_RE = re.compile(r"^enl\.?\s*rit", re.IGNORECASE)
RANGE_RE = re.compile(r"^(\d+(?:[,.]\d+)?)\s*[-–]\s*(\d+(?:[,.]\d+)?)\s*([a-zåäö.]*)$", re.IGNORECASE)
FIXED_RE = re.compile(r"^(\d+(?:[,.]\d+)?)\s*([a-zåäö.²³]*)$", re.IGNORECASE)
# en mängd har alltid en enhet: ett ensamt tal i MÄNGD-kolumnen är ett anslutningsmått eller liknande
# ("Ansl. nr. 25")
UNITS = {"st": "st", "st.": "st", "stk": "st", "m": "m", "m.": "m", "m2": "m2", "m²": "m2", "kg": "kg"}


@dataclass(frozen=True)
class ParsedQuantity:
    mode: str  # fixed | per_drawing | range | regulated
    quantity: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    unit: str | None
    text: str


def _num(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


def parse_quantity(text: str | None) -> ParsedQuantity | None:
    t = (text or "").strip()
    if not t:
        return None
    if PER_DRAWING_RE.match(t):
        return ParsedQuantity("per_drawing", None, None, None, None, t)
    if t.upper() == "R":
        return ParsedQuantity("regulated", None, None, None, None, t)
    m = RANGE_RE.match(t)
    if m:
        return ParsedQuantity(
            "range", None, _num(m.group(1)), _num(m.group(2)), UNITS.get(m.group(3).lower(), m.group(3)), t
        )
    m = FIXED_RE.match(t)
    if m and m.group(2).lower() in UNITS:
        return ParsedQuantity("fixed", _num(m.group(1)), None, None, UNITS[m.group(2).lower()], t)
    return None
