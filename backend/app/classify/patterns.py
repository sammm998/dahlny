"""Deterministisk tolkning av ritningsnummer, skala, uppdragsnummer och datum (SPEC 6.1.5).

Mönstren ligger i config/documents.yaml. Funktionerna här läser bara det som står; de kompletterar aldrig.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config.settings import load_documents_config


@dataclass(frozen=True)
class ScaleRatio:
    denominator: int
    paper: str | None  # "A1" om skalan anges för en viss pappersstorlek, annars None

    @property
    def text(self) -> str:
        return f"1:{self.denominator}" + (f" ({self.paper})" if self.paper else "")


def drawing_numbers(text: str) -> list[str]:
    found: list[str] = []
    for pattern in load_documents_config().drawing_number.patterns:
        for m in re.finditer(pattern, text):
            if m.group("no") not in found:
                found.append(m.group("no"))
    return found


def scale_ratios(text: str) -> list[ScaleRatio]:
    """Alla skalor i en titelblocks- eller förteckningstext, t.ex. '1:50 (A1) 1:100 (A3)'."""
    return [
        ScaleRatio(int(m.group("n")), m.group("paper"))
        for m in re.finditer(load_documents_config().scale.ratio, text)
    ]


def is_no_scale(text: str) -> bool:
    return text.strip().upper() in {s.upper() for s in load_documents_config().scale.none_markers}


def project_number(text: str) -> str | None:
    m = re.search(load_documents_config().project_no, text, re.IGNORECASE)
    return m.group("no") if m else None


def dates(text: str) -> list[str]:
    return [m.group("date") for m in re.finditer(load_documents_config().date, text)]
