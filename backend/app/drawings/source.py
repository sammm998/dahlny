"""Gränssnittet för ritningsmängder (SPEC 6.4.7, 7.5): `DrawingQuantitySource`.

En källa – vvs_engine i dag, en extern tjänst som FutureCalc senare – läser en ritnings-PDF och lämnar
mängder i VS-Kalkyls form. Resultatet är utkast (`*Draft`) som inte är sparade i databasen:
avstämningen och granskningen (SPEC 6.5, 9) avgör vad som blir PipeRun och Symbol. Ingen källa får räkna
om eller rätta en meter i tysthet; allt den är osäker på bärs som flaggor.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

SymbolKind = Literal["riser", "tag"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceRef(_Frozen):
    """Spårbarhet enligt SPEC 2.3: {document_id, page, bbox, method, model, confidence} + källans evidens."""

    document_id: uuid.UUID | None = None
    page: int  # 1-baserat sidnummer i dokumentet
    bbox: tuple[float, float, float, float] | None = None  # PDF-punkter, origo uppe till vänster
    method: str
    model: str | None = None  # källans namn och version, t.ex. "vvs_engine 0.1.0 @7f8248a"
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: dict[str, Any] = Field(default_factory=dict)


class SheetScale(_Frozen):
    page: int
    state: str  # källans eget tillstånd, t.ex. VERIFIED / TEXT_ONLY / CONFLICT
    verified: bool
    meters_per_pt: float | None
    reason: str | None
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class PipeRunDraft(_Frozen):
    page: int
    designation: str
    system: str | None
    material: str | None
    dim: str | None
    length_m_horizontal: float
    length_m_vertical: float | None  # None = "ej bestämd" (SPEC 6.4.3 j) – aldrig 0 när det är okänt
    length_m_total: float | None
    ambiguous_m: float
    in_hatched_area_m: float
    riser_count: int
    state: str
    confidence: float = Field(ge=0, le=1)
    segment_ids: list[str]
    flags: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef]


class OutsideContractDraft(_Frozen):
    """En sträcka bortom en entreprenadgräns (`ENTR. GRÄNS`): egen kategori, varken mängd eller otilldelat."""

    page: int
    designation: str | None  # röret som korsar gränsen, om det har ett namn
    system: str | None
    dim: str | None
    length_m: float | None
    boundary_point: tuple[float, float]
    note: str
    source_refs: list[SourceRef]


class SymbolDraft(_Frozen):
    page: int
    kind: SymbolKind
    tag: str | None
    bbox: tuple[float, float, float, float] | None
    read_method: str
    confidence: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef]


class LegendEntryDraft(_Frozen):
    page: int
    code: str
    description: str
    role: str | None
    flags: list[str] = Field(default_factory=list)


class SheetCoverage(_Frozen):
    page: int
    drawn_m: float | None
    confirmed_m: float | None
    ambiguous_m: float | None
    unowned_m: float | None
    outside_contract_m: float | None = None  # bortom entreprenadgräns – ingår varken i mängd eller otilldelat

    @property
    def unassigned_fraction(self) -> float | None:
        """Andel otilldelat av den ritade längden innanför entreprenadgränsen."""
        inside = (self.drawn_m or 0.0) - (self.outside_contract_m or 0.0)
        if inside <= 0:
            return None
        return ((self.unowned_m or 0.0) + (self.ambiguous_m or 0.0)) / inside


class SheetTakeoff(_Frozen):
    page: int
    width_pt: float | None
    height_pt: float | None
    scale: SheetScale | None
    coverage: SheetCoverage | None
    pipe_runs: list[PipeRunDraft]
    symbols: list[SymbolDraft]
    legend: list[LegendEntryDraft]
    designations_read: list[str]  # all text källan läste som beteckningar, för mätning mot facit
    outside_contract: list[OutsideContractDraft] = Field(default_factory=list)


class DrawingTakeoff(_Frozen):
    source: str
    source_version: str
    input_sha256: str
    sheets: list[SheetTakeoff]
    warnings: list[str] = Field(default_factory=list)


class DrawingSourceError(RuntimeError):
    """Källan kunde inte köras eller lämnade ett resultat som inte går att lita på."""


class DrawingQuantitySource(Protocol):
    name: str

    def analyze(self, pdf_path: Path, work_dir: Path) -> DrawingTakeoff: ...
