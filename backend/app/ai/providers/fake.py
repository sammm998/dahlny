"""Skriptad leverantör för tester och offline-körning. Inga nätverksanrop."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.ai.datatypes import ProviderRefusal, ProviderRequest, ProviderResponse

Reply = str | dict[str, Any] | Exception | Callable[[ProviderRequest], str | dict[str, Any]]


@dataclass
class FakeProvider:
    """Returnerar svar i tur och ordning, per modell. Ett dict serialiseras till JSON;
    en Exception kastas; en funktion anropas med requesten."""

    replies: dict[str, list[Reply]] = field(default_factory=dict)
    name: str = "fake"
    calls: list[ProviderRequest] = field(default_factory=list)
    stop_reason: str = "end_turn"

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        queue = self.replies.get(request.model)
        if not queue:
            raise AssertionError(f"FakeProvider: inget svar köat för {request.model}")
        reply = queue.pop(0)
        if isinstance(reply, ProviderRefusal):
            raise reply
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(request)
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return ProviderResponse(
            text=text,
            served_model=request.model,
            stop_reason=self.stop_reason,
            tokens_in=100,
            tokens_out=20,
            tokens_cache_read=0,
            tokens_cache_write=0,
            raw={"fake": True, "text": text},
        )
