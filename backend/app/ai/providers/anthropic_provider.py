"""Anthropic-adapter (primär leverantör, SPEC 7.1).

- Strukturerat svar via `output_config.format` (json_schema). Tvingat tool_choice används inte –
  det avvisas av opus-5-5/sonnet-5-5/fable-5-1.
- temperature skickas inte till modeller där det inte stöds (alla nuvarande Claude-modeller).
- Prompt caching: brytpunkter på systemprompten och på sista kontextblocket (legend/TB-text).
- Serverside fallback vid refusal är valbar i models.yaml; svarande modell loggas.
"""

from __future__ import annotations

from typing import Any

import anthropic

from app.ai.datatypes import (
    ImagePart,
    ProviderError,
    ProviderNotConfigured,
    ProviderRefusal,
    ProviderRequest,
    ProviderResponse,
    TextPart,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        max_retries: int,
        timeout_s: float,
        server_side_fallback: bool = False,
        api_key: str | None = None,
        base_url: str | None = None,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        if client is None:
            try:
                # Nyckel och adress skickas uttryckligen när de är satta i VS-Kalkyls inställningar, så att
                # SDK:n inte plockar upp miljöns ANTHROPIC_* (som i molnmiljön tillhör Claude Code).
                client = anthropic.Anthropic(
                    api_key=api_key, base_url=base_url, max_retries=max_retries, timeout=timeout_s
                )
            except anthropic.AnthropicError as exc:  # saknad nyckel m.m.
                raise ProviderNotConfigured(f"Anthropic-klienten kunde inte skapas: {exc}") from exc
        self._client = client
        self._fallback = server_side_fallback

    def build_params(self, request: ProviderRequest) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for i, block in enumerate(request.context_blocks):
            item: dict[str, Any] = {"type": "text", "text": block}
            if i == len(request.context_blocks) - 1:
                item["cache_control"] = _EPHEMERAL
            content.append(item)
        for part in request.parts:
            if isinstance(part, TextPart):
                content.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                content.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": part.media_type, "data": part.b64()},
                    }
                )
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(request.json_schema)}
        }
        if request.effort is not None:
            output_config["effort"] = request.effort
        return {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": [{"type": "text", "text": request.system, "cache_control": _EPHEMERAL}],
            "messages": [{"role": "user", "content": content}],
            "output_config": output_config,
        }

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        params = self.build_params(request)
        try:
            if self._fallback:
                message: Any = self._client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                message = self._client.messages.create(**params)
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"Anthropic {exc.status_code}: {exc.message}", status_code=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"Anthropic nätverksfel: {exc}") from exc
        except anthropic.CredentialsError as exc:
            raise ProviderNotConfigured(f"Anthropic-inloggningsuppgifterna kunde inte läsas: {exc}") from exc
        except TypeError as exc:
            # SDK:n upptäcker saknade inloggningsuppgifter först när requesten byggs.
            if "authentication" not in str(exc):
                raise
            raise ProviderNotConfigured(
                "Inga Anthropic-inloggningsuppgifter "
                "(sätt DAHLNY_ANTHROPIC_API_KEY eller ANTHROPIC_API_KEY)"
            ) from exc

        raw: dict[str, Any] = message.model_dump(mode="json")
        if message.stop_reason == "refusal":
            details = raw.get("stop_details") or {}
            raise ProviderRefusal(
                f"Modellen avböjde (kategori: {details.get('category')})", served_model=message.model, raw=raw
            )
        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        return ProviderResponse(
            text=text,
            served_model=message.model,
            stop_reason=message.stop_reason,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            tokens_cache_read=usage.cache_read_input_tokens,
            tokens_cache_write=usage.cache_creation_input_tokens,
            raw=raw,
        )
