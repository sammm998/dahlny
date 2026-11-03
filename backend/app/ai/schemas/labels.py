"""Svarsscheman för T5 (etiketter i en ritningsbit, SPEC 7.4) och T5R (omläsning av en etikett)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TileLabel(BaseModel):
    """Kompakt (prompt v2): ledarlinjer och understrykning tas ur geometrin i motorn, inte ur bilden.
    Utdata-tokens är huvuddelen av kostnaden för T5 (beslut 2026-11-02: under 1 USD per ritning)."""

    text: str = Field(description="Etiketten tecken för tecken, exakt som den står")
    bbox_px: list[float] = Field(description="[x0, y0, x1, y1] i bildens pixlar", min_length=4, max_length=4)
    rotation_deg: float = Field(description="Läsriktning: 0 vågrät, 90 eller -90 lodrät")
    confidence: float = Field(ge=0, le=1)
    uncertain_chars: list[str] = Field(description="Tecken i texten du är osäker på")


class TileLabels(BaseModel):
    labels: list[TileLabel]
    tile_has_cut_text: bool = Field(description="Skär bildens kant genom någon text?")


class LabelReread(BaseModel):
    text: str = Field(description="Etiketten tecken för tecken, exakt som den står i bilden")
    choice: Literal["first", "second", "neither"] = Field(
        description="Vilken av de två föreslagna läsningarna stämmer exakt, eller ingen"
    )
    confidence: float = Field(ge=0, le=1)
    reason: str


class TileTriage(BaseModel):
    """T5T: sortering och läsning av en ritningsbit."""

    kind: Literal["empty", "simple", "hard"] = Field(
        description="empty: ingen text; simple: få, tydliga, vågräta etiketter utan linjer genom texten; "
        "hard: allt annat"
    )
    reason: str = Field(description="Kort motivering")
    labels: list[TileLabel] = Field(description="All text i biten (tom lista om kind är empty)")
    tile_has_cut_text: bool = Field(description="Skär bildens kant genom någon text?")
