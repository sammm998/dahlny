"""Mängdlista ur ritningsmängder: en rad per system × material × dimension (beslut 2026-11-03).

- Beteckningar som bara skiljer sig i suffix summeras på samma rad: `KV01-K1-15-W40` och `KV01-K1-15-W` hamnar
  under `KV01-K1-15`. Fördelningen per suffix visas som underrader. Ett suffix som varken projektets legend
  eller standardtabellen känner flaggas `UNKNOWN_LABEL_TOKEN` (fråga till konsulten) – det tolkas inte.
- `L` direkt efter dimensionen (`110L`, luftning) är grammatikens eget suffix och räknas som känt.
- Saknar en rad material och systemet har exakt ett material i projektet (TB och ritningens etiketter,
  app/tb/system_materials.py) fylls det i med källa och konfidens
  `quantities.material_from_system_confidence`.
  Har systemet flera material lämnas det tomt och raden flaggas `MATERIAL_UNRESOLVED`.
- Meter är bekräftad horisontell längd (`length_m_horizontal`); tvetydig längd redovisas för sig och räknas
  aldrig in.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.config.settings import load_label_grammar, load_thresholds
from app.drawings.source import PipeRunDraft
from app.tb.system_materials import SystemMaterialIndex

AIR_SUFFIX = "L"  # 110L: luftning (label_grammar.yaml)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SuffixRow(_Frozen):
    suffix: str  # "" = utan suffix
    designations: list[str]
    length_m: float
    ambiguous_m: float
    flags: list[str] = Field(default_factory=list)


class QuantityRow(_Frozen):
    system: str
    material: str | None
    material_source: str | None  # etikett | TB | ritning | None
    material_confidence: float | None
    dim: str | None
    length_m: float
    ambiguous_m: float
    pages: list[int]
    sub_rows: list[SuffixRow]
    flags: list[str] = Field(default_factory=list)

    @property
    def base(self) -> str:
        return "-".join(p for p in (self.system, self.material, self.dim) if p)


def _suffixes(designation: str) -> tuple[str, ...]:
    m = re.match(load_label_grammar().pipe.pattern, designation)
    if not m:
        return ()
    found = [s for s in (m.group("suffixes") or "").split("-") if s]
    dim = m.group("dim") or ""
    if dim.endswith(AIR_SUFFIX):
        found.insert(0, AIR_SUFFIX)
    return tuple(found)


def _dim(run: PipeRunDraft) -> str | None:
    return run.dim.rstrip(AIR_SUFFIX) if run.dim else None


def summarize(
    runs: Iterable[PipeRunDraft], *, known_codes: set[str], system_materials: SystemMaterialIndex
) -> list[QuantityRow]:
    conf = load_thresholds().get("quantities.material_from_system_confidence")
    groups: dict[tuple[str, str | None, str | None], list[PipeRunDraft]] = defaultdict(list)
    inferred: dict[str, tuple[str, str] | None] = {}
    for run in runs:
        system = run.system or "?"
        material = run.material
        if material is None:
            if system not in inferred:
                one = system_materials.single(system)
                inferred[system] = (one[0], one[1]) if one else None
            got = inferred[system]
            material = got[0] if got else None
        groups[(system, material, _dim(run))].append(run)
    rows = []
    for (system, material, dim), members in sorted(
        groups.items(), key=lambda kv: tuple(str(k) for k in kv[0])
    ):
        by_suffix: dict[tuple[str, ...], list[PipeRunDraft]] = defaultdict(list)
        for run in members:
            by_suffix[_suffixes(run.designation)].append(run)
        subs = []
        for suffix, rs in sorted(by_suffix.items()):
            unknown = [s for s in suffix if s != AIR_SUFFIX and s not in known_codes]
            subs.append(
                SuffixRow(
                    suffix="-".join(suffix),
                    designations=sorted({r.designation for r in rs}),
                    length_m=round(sum(r.length_m_horizontal for r in rs), 3),
                    ambiguous_m=round(sum(r.ambiguous_m for r in rs), 3),
                    flags=[f"UNKNOWN_LABEL_TOKEN:{s}" for s in unknown],
                )
            )
        flags = sorted({f for s in subs for f in s.flags})
        source: str | None = None
        confidence: float | None = None
        if material is not None:
            filled = [r for r in members if r.material is None]
            got = inferred.get(system)
            sources = {"etikett"} if len(filled) < len(members) else set()
            if filled and got is not None:
                sources.add(got[1])
                confidence = conf  # lägsta konfidensen bland raderna: den ifyllda
                flags.append("MATERIAL_FROM_SYSTEM")
            source = "+".join(sorted(sources)) or None
        else:
            flags.append("MATERIAL_UNRESOLVED")
        rows.append(
            QuantityRow(
                system=system,
                material=material,
                material_source=source,
                material_confidence=confidence,
                dim=dim,
                length_m=round(sum(s.length_m for s in subs), 3),
                ambiguous_m=round(sum(s.ambiguous_m for s in subs), 3),
                pages=sorted({r.page for r in members}),
                sub_rows=subs if len(subs) > 1 or any(s.suffix for s in subs) else [],
                flags=flags,
            )
        )
    return rows
