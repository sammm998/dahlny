"""Deterministisk tolkning av måttangivelser i TB-text (t.ex. "300x300x192", "300 x 300 x 400mm").

Används av avstämningen (TB_SELF_CONTRADICTION, SPEC 6.5) för att jämföra mått som står på olika ställen för
samma post. Två skrivsätt av samma mått ska ge samma värde: blanksteg, gemener/versaler, multiplikationstecken
och enhet normaliseras. Allt räknas om till millimeter. Inget gissas: en sträng som inte är ett entydigt mått
ger ingen träff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_UNIT_TO_MM = {"mm": Decimal(1), "cm": Decimal(10), "m": Decimal(1000)}
_NUM = r"\d+(?:[.,]\d+)?"
_UNIT = r"(?:mm|cm|m)(?![a-zåäö])"
_SEP = r"\s*[x×X*]\s*"
# Två eller tre värden, enhet efter valfritt värde (oftast bara efter det sista).
_DIMENSION_RE = re.compile(
    rf"(?<![\d.,])(?P<a>{_NUM})\s*(?P<ua>{_UNIT})?{_SEP}(?P<b>{_NUM})\s*(?P<ub>{_UNIT})?"
    rf"(?:{_SEP}(?P<c>{_NUM})\s*(?P<uc>{_UNIT})?)?(?![\d.,]*\d)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Dimension:
    """Ett mått i millimeter, med originaltexten och var i texten det stod."""

    values_mm: tuple[Decimal, ...]
    raw: str
    start: int
    end: int

    @property
    def normalized(self) -> str:
        return "x".join(_fmt(v) for v in self.values_mm) + " mm"


def _fmt(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _to_decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", "."))


def find_dimensions(text: str) -> list[Dimension]:
    """Alla mått (2 eller 3 värden) i texten, i textordning."""
    found: list[Dimension] = []
    for m in _DIMENSION_RE.finditer(text):
        numbers = [m.group(k) for k in ("a", "b", "c") if m.group(k) is not None]
        units = [m.group(k) for k in ("ua", "ub", "uc")[: len(numbers)]]
        given = {u.lower() for u in units if u}
        if len(given) > 1:
            continue  # blandade enheter i samma mått – tolkas inte, granskas manuellt
        factor = _UNIT_TO_MM[given.pop()] if given else Decimal(1)  # utan enhet: mm (AMA-praxis)
        values = tuple(_to_decimal(n) * factor for n in numbers)
        found.append(Dimension(values_mm=values, raw=m.group(0).strip(), start=m.start(), end=m.end()))
    return found


def same_dimension(a: Dimension, b: Dimension) -> bool:
    return a.values_mm == b.values_mm
