"""Scheman för facitfiler i eval/projects/{namn}/expected/ (SPEC 11).

Facit är handskrivet ur SPEC Bilaga A och valideras här så att ett skrivfel i facit fallerar
högljutt i stället för att ge fel mätvärden.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuantityMode = Literal["fixed", "per_drawing", "range", "regulated"]
Severity = Literal["info", "warning", "critical"]
LabelKind = Literal[
    "pipe", "object", "schematic_valve", "height_cl", "height_vg", "slope", "dimension", "free_text"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedSpecItem(_Strict):
    ref: str  # radnummer i Bilaga A.1, t.ex. "5"
    designation: str | None
    parent_designation: str | None = None  # "Härtill"-tillbehör under en sanitetsenhet
    product: str
    article_no: str | None = None
    rsk: str | None = Field(default=None, pattern=r"^\d{7}$")
    quantity: float | None
    quantity_range: tuple[float, float] | None = None
    unit: str | None
    quantity_mode: QuantityMode

    @model_validator(mode="after")
    def _consistent_quantity(self) -> ExpectedSpecItem:
        if self.quantity_mode == "fixed" and self.quantity is None:
            raise ValueError(f"rad {self.ref}: fixed kräver quantity")
        if self.quantity_mode == "range" and self.quantity_range is None:
            raise ValueError(f"rad {self.ref}: range kräver quantity_range")
        if self.quantity_mode == "per_drawing" and self.quantity is not None:
            raise ValueError(f"rad {self.ref}: per_drawing ska inte ha quantity")
        return self


class SpecItemsFacit(_Strict):
    source: str
    items: list[ExpectedSpecItem]
    aggregates: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ExpectedProjectRule(_Strict):
    category: str
    text: str


class ProjectRulesFacit(_Strict):
    source: str
    rules: list[ExpectedProjectRule]


class ExpectedDeviation(_Strict):
    id: str
    number: int  # numret i Bilaga A.3
    rule_id: str
    severity: Severity
    subject: str
    description: str
    expected_by_phase: int


class DeviationsFacit(_Strict):
    source: str
    deviations: list[ExpectedDeviation]


class ExpectedLabel(_Strict):
    text: str
    kind: LabelKind
    parse_status: Literal["ok", "unknown_token"] = "ok"
    note: str | None = None


class DrawingLabels(_Strict):
    drawing_no: str
    title: str
    labels: list[ExpectedLabel]


class LabelsFacit(_Strict):
    source: str
    drawings: list[DrawingLabels]
    notes: list[str] = Field(default_factory=list)


class ExpectedSymbolCount(_Strict):
    group: str
    kind: str
    tag: str | None
    count: int = Field(ge=0)
    source: Literal["plan", "schematic"]
    note: str | None = None


class SymbolsFacit(_Strict):
    source: str
    counts: list[ExpectedSymbolCount]
    legend_tables: list[str]
    notes: list[str] = Field(default_factory=list)


class ExpectedDocument(_Strict):
    filename: str
    kind: str | None
    pages: int
    project_no: str | None = None
    date: str | None = None
    note: str | None = None


class ExpectedPage(_Strict):
    filename: str
    page_no: int
    kind: str
    format: str
    paper_size: str
    drawing_no: str | None
    level_name: str | None = None
    scale_text: str | None
    effective_scale: str | None = None
    project_no: str | None
    date: str | None


class ExpectedListDrawing(_Strict):
    drawing_no: str
    title: str
    scale_text: str


class ExpectedDrawingList(_Strict):
    page: dict[str, str | int]
    project_no: str
    drawings: list[ExpectedListDrawing]
    documents: list[str]


class ExpectedPhase1Deviation(_Strict):
    rule_id: str
    severity: Severity
    subject: str
    pages: list[int]
    note: str


class PagesFacit(_Strict):
    source: str
    documents: list[ExpectedDocument]
    pages: list[ExpectedPage]
    drawing_list: ExpectedDrawingList
    expected_phase1_deviations: list[ExpectedPhase1Deviation]


class InputFile(_Strict):
    filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: int | None = None
    description: str


class InputManifest(_Strict):
    project: str
    confidential: bool
    files: list[InputFile]


class ProjectFacit(_Strict):
    pages: PagesFacit
    spec_items: SpecItemsFacit
    project_rules: ProjectRulesFacit
    deviations: DeviationsFacit
    labels: LabelsFacit
    symbols: SymbolsFacit


def _read(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_facit(expected_dir: Path) -> ProjectFacit:
    return ProjectFacit(
        pages=PagesFacit.model_validate(_read(expected_dir / "pages.json")),
        spec_items=SpecItemsFacit.model_validate(_read(expected_dir / "spec_items.json")),
        project_rules=ProjectRulesFacit.model_validate(_read(expected_dir / "project_rules.json")),
        deviations=DeviationsFacit.model_validate(_read(expected_dir / "deviations.json")),
        labels=LabelsFacit.model_validate(_read(expected_dir / "labels.json")),
        symbols=SymbolsFacit.model_validate(_read(expected_dir / "symbols.json")),
    )


def load_manifest(input_dir: Path) -> InputManifest:
    return InputManifest.model_validate(_read(input_dir / "MANIFEST.json"))
