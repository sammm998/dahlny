"""Vilket material ett system har i projektet, enligt TB och ritningens etiketter (beslut 2026-11-03).

TB skriver systemets material som en rörbeteckning utan dimension i sina PNU-avsnitt – `PNU.215 … L9-S13
Tryckluft Enl ritn`, `KV01-K1 Tappkallvatten Enl ritn` – och ritningens etiketter bär det i själva
beteckningen (`L9-S13-28`). Båda läses med samma beteckningsgrammatik (label_grammar.yaml); ingenting
tolkas utöver den.

Har ett system exakt ett material i projektet fylls det i på mängdrader som saknar material
(`quantities.material_from_system_confidence`), annars lämnas det tomt och flaggas `MATERIAL_UNRESOLVED`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.config.settings import load_label_grammar

TB = "TB"
DRAWING = "ritning"


@dataclass(frozen=True)
class SystemMaterial:
    system: str
    material: str
    source: str  # TB | ritning
    page: int | None
    text: str  # beteckningen som den stod


def _parts(code: str) -> tuple[str, str | None, str | None] | None:
    m = re.match(load_label_grammar().pipe.pattern, code)
    if not m:
        return None
    return m.group("system"), m.group("material"), m.group("dim")


def from_tb_pages(pages: Iterable[tuple[int, str]]) -> list[SystemMaterial]:
    """`SYSTEM-MATERIAL` utan dimension som eget ord i TB-texten (PNU-avsnittens rubrikrader)."""
    out = []
    for page, text in pages:
        for word in re.findall(r"[A-ZÅÄÖ0-9]+(?:-[A-ZÅÄÖ0-9]+)+", text):
            parts = _parts(word)
            if parts and parts[1] and parts[2] is None:
                out.append(SystemMaterial(parts[0], parts[1], TB, page, word))
    return out


def from_designations(designations: Iterable[tuple[int, str]]) -> list[SystemMaterial]:
    """Ritningens rörbeteckningar som bär material (`L9-S13-28`, `KV01-K1-15-W40`)."""
    out = []
    for page, code in designations:
        parts = _parts(code)
        if parts and parts[1]:
            out.append(SystemMaterial(parts[0], parts[1], DRAWING, page, code))
    return out


@dataclass(frozen=True)
class SystemMaterialIndex:
    """Material per system i projektet, med varifrån varje uppgift kommer."""

    found: tuple[SystemMaterial, ...]

    @classmethod
    def build(cls, *sources: Iterable[SystemMaterial]) -> SystemMaterialIndex:
        return cls(tuple(sm for src in sources for sm in src))

    def materials(self, system: str) -> set[str]:
        return {sm.material for sm in self.found if sm.system == system}

    def single(self, system: str) -> tuple[str, str, list[SystemMaterial]] | None:
        """(material, källa, belägg) när systemet har exakt ett material; källan är TB om TB säger det."""
        mats = self.materials(system)
        if len(mats) != 1:
            return None
        evidence = [sm for sm in self.found if sm.system == system]
        source = TB if any(sm.source == TB for sm in evidence) else DRAWING
        return next(iter(mats)), source, evidence
