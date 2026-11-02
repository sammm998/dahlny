"""Providerneutrala typer för AI-anrop (SPEC 7.2, 7.5)."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config.settings import Effort

ImageMediaType = Literal["image/png", "image/jpeg", "image/webp", "image/gif"]


@dataclass(frozen=True)
class TextPart:
    text: str

    def fingerprint(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass(frozen=True)
class ImagePart:
    """En bild (t.ex. en ritningstile). Skickas som PNG enligt SPEC 7.2."""

    data: bytes
    media_type: ImageMediaType = "image/png"
    label: str | None = None  # t.ex. "page3_tile_2_4" – för loggning, inte för modellen

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def b64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    def fingerprint(self) -> dict[str, Any]:
        # Bildens bytes loggas aldrig; hash räcker för cache och spårbarhet.
        return {
            "type": "image",
            "media_type": self.media_type,
            "sha256": self.sha256,
            "bytes": len(self.data),
        }


ContentPart = TextPart | ImagePart


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    system: str
    # Stora återkommande block (legend, TB-text) som ska prompt-cachas. Läggs före `parts`.
    context_blocks: tuple[str, ...]
    parts: tuple[ContentPart, ...]
    json_schema: dict[str, Any]
    schema_name: str
    max_tokens: int
    effort: Effort | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    served_model: str
    stop_reason: str | None
    tokens_in: int | None  # icke-cachade indatatokens
    tokens_out: int | None
    tokens_cache_read: int | None = None
    tokens_cache_write: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """API-fel som kvarstår efter SDK:ns egna omförsök (backoff)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderRefusal(Exception):
    """Modellen avböjde (stop_reason=refusal)."""

    def __init__(self, message: str, *, served_model: str | None = None, raw: dict[str, Any] | None = None):
        super().__init__(message)
        self.served_model = served_model
        self.raw = raw or {}


class ProviderNotConfigured(Exception):
    """Adaptern finns men saknar nyckel/konfiguration eller är inte godkänd (ÖPPEN FRÅGA 11)."""
