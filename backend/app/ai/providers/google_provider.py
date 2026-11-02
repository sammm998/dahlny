"""Google-adapter (kandidat i bakeoff för T5 och skannad TB, SPEC 7.5).

Stub: implementeras när leverantören är godkänd (ÖPPEN FRÅGA 11) och SDK/modell valts.
Gränssnittet är detsamma som för övriga adaptrar så att AIClient inte behöver ändras.
"""

from __future__ import annotations

from app.ai.datatypes import ProviderNotConfigured, ProviderRequest, ProviderResponse


class GoogleProvider:
    name = "google"

    def __init__(self, **_: object) -> None:
        pass

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderNotConfigured(
            "Google-adaptern är inte implementerad ännu – leverantören väntar på godkännande "
            "(SPEC 14, fråga 11)."
        )
