"""Svarsscheman för T1 (sidklassning) och T2 (titelblock), SPEC 6.1.4–5."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PageKind = Literal["tb", "drawing_list", "plan", "schematic", "section", "detail", "legend_only", "other"]


class PageClassification(BaseModel):
    kind: PageKind = Field(description="Sidans typ")
    confidence: float = Field(ge=0, le=1, description="Konfidens 0–1")
    reason: str = Field(description="Kort skäl på svenska, med det som syns på sidan")


class TitleBlockReading(BaseModel):
    found: bool = Field(description="Finns ett titelblock i bilden?")
    drawing_no: str | None = Field(description="Ritningsnumret tecken för tecken, t.ex. W-50-1-1000")
    title_lines: list[str] = Field(description="Innehållsraderna i ordning, ordagrant (t.ex. HUS 1, PLAN 1)")
    level_name: str | None = Field(description="Plan/våning om det står, t.ex. PLAN 1")
    scale_text: str | None = Field(description="Skalfältet ordagrant, t.ex. '1:50 (A1) 1:100 (A3)'")
    project_no: str | None = Field(description="Uppdragsnummer ordagrant")
    date: str | None = Field(description="Ritningsdatum ordagrant (ÅÅÅÅ-MM-DD)")
    revision: str | None = Field(description="Revision om ifylld, annars null")
    consultant: str | None = Field(description="Konsultföretag")
    confidence: float = Field(ge=0, le=1)
    uncertain_fields: list[str] = Field(description="Fält där något tecken är osäkert")
