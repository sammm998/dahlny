"""OpenAI-adapter (kandidat i bakeoff för T5/T8, SPEC 7.5). Samma gränssnitt som Anthropic-adaptern.

Används först när leverantören godkänts av IT/juridik (ÖPPEN FRÅGA 11) och modell-ID/pris verifierats.
"""

from __future__ import annotations

import copy
from typing import Any

import openai

from app.ai.datatypes import (
    ImagePart,
    ProviderError,
    ProviderNotConfigured,
    ProviderRefusal,
    ProviderRequest,
    ProviderResponse,
    TextPart,
)


def strict_openai_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict-läge kräver additionalProperties=false och att alla egenskaper är required."""
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            node.pop("default", None)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(out)
    return out


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, max_retries: int, timeout_s: float, client: openai.OpenAI | None = None) -> None:
        if client is None:
            try:
                client = openai.OpenAI(max_retries=max_retries, timeout=timeout_s)
            except openai.OpenAIError as exc:
                raise ProviderNotConfigured(f"OpenAI-klienten kunde inte skapas: {exc}") from exc
        self._client = client

    def build_params(self, request: ProviderRequest) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": b} for b in request.context_blocks]
        for part in request.parts:
            if isinstance(part, TextPart):
                content.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                url = f"data:{part.media_type};base64,{part.b64()}"
                content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
        params: dict[str, Any] = {
            "model": request.model,
            "max_completion_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "schema": strict_openai_schema(request.json_schema),
                    "strict": True,
                },
            },
        }
        if request.temperature is not None:
            params["temperature"] = request.temperature
        return params

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        try:
            completion = self._client.chat.completions.create(**self.build_params(request))
        except openai.APIStatusError as exc:
            raise ProviderError(
                f"OpenAI {exc.status_code}: {exc.message}", status_code=exc.status_code
            ) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(f"OpenAI nätverksfel: {exc}") from exc

        raw: dict[str, Any] = completion.model_dump(mode="json")
        choice = completion.choices[0]
        if choice.message.refusal:
            raise ProviderRefusal(choice.message.refusal, served_model=completion.model, raw=raw)
        usage = completion.usage
        cached = 0
        if usage and usage.prompt_tokens_details and usage.prompt_tokens_details.cached_tokens:
            cached = usage.prompt_tokens_details.cached_tokens
        stop = "max_tokens" if choice.finish_reason == "length" else choice.finish_reason
        return ProviderResponse(
            text=choice.message.content or "",
            served_model=completion.model,
            stop_reason=stop,
            tokens_in=(usage.prompt_tokens - cached) if usage else None,
            tokens_out=usage.completion_tokens if usage else None,
            tokens_cache_read=cached if usage else None,
            tokens_cache_write=0 if usage else None,
            raw=raw,
        )
