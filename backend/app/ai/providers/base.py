from __future__ import annotations

from typing import Protocol

from app.ai.datatypes import ProviderRequest, ProviderResponse


class Provider(Protocol):
    """Ett enda anrop mot en leverantör. Retry vid nätverksfel sköts av leverantörens SDK;
    valideringsretry, eskalering, cache och loggning sköts av AIClient."""

    name: str

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...
