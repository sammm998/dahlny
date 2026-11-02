from __future__ import annotations

from pydantic import BaseModel, Field


class PingResult(BaseModel):
    """Svarsschema för T0 (rökprov)."""

    echo: str = Field(description="Kontrollsträngen exakt som den skrevs")
    confidence: float = Field(ge=0, le=1, description="Konfidens 0–1")
    reason: str = Field(description="Kort motivering på svenska")
