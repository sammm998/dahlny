"""Adaptrarna testas mot leverantörernas riktiga SDK:er med en httpx2.MockTransport (SDK:ernas
transport) – så att serialiseringen (output_config, cache_control, bilder)
kontrolleras utan nätverk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from app.ai.datatypes import (
    ImagePart,
    ProviderError,
    ProviderNotConfigured,
    ProviderRefusal,
    ProviderRequest,
    TextPart,
)
from app.ai.providers.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from app.ai.providers.openai_provider import OpenAIProvider, strict_openai_schema
from app.ai.schemas.t0 import PingResult

REQUEST = ProviderRequest(
    model="claude-opus-5-5",
    system="Du läser svenska VVS-handlingar.",
    context_blocks=("LEGEND: K1 = Koppar, hårda",),
    parts=(TextPart("Läs etiketten"), ImagePart(b"\x89PNG fake", label="tile")),
    json_schema=PingResult.model_json_schema(),
    schema_name="PingResult",
    max_tokens=1024,
    effort="high",
    temperature=None,
)


def anthropic_message(
    stop_reason: str = "end_turn", text: str = '{"echo":"a","confidence":1,"reason":"r"}'
) -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": {"type": "refusal", "category": "cyber", "explanation": None}
        if stop_reason == "refusal"
        else None,
        "usage": {
            "input_tokens": 50,
            "output_tokens": 10,
            "cache_read_input_tokens": 400,
            "cache_creation_input_tokens": 0,
        },
    }


def mock_anthropic(handler: Any) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="test", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )


@pytest.mark.parametrize("fallback", [False, True])
def test_anthropic_request_shape(fallback: bool) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        seen["headers"] = request.headers
        return httpx2.Response(200, json=anthropic_message())

    provider = AnthropicProvider(
        max_retries=0, timeout_s=10, server_side_fallback=fallback, client=mock_anthropic(handler)
    )
    resp = provider.complete(REQUEST)

    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert "temperature" not in body
    assert "tool_choice" not in body  # tvingat verktygsval avvisas av nuvarande modeller
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = body["messages"][0]["content"]
    assert content[0]["text"].startswith("LEGEND") and content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[2]["type"] == "image" and content[2]["source"]["media_type"] == "image/png"
    if fallback:
        assert body["fallbacks"] == "default"
        assert FALLBACK_BETA in seen["headers"]["anthropic-beta"]
    else:
        assert "fallbacks" not in body

    assert resp.served_model == "claude-opus-5-5"
    assert resp.tokens_in == 50 and resp.tokens_out == 10 and resp.tokens_cache_read == 400
    assert PingResult.model_validate_json(resp.text).echo == "a"


def test_anthropic_refusal_raises() -> None:
    provider = AnthropicProvider(
        max_retries=0,
        timeout_s=10,
        client=mock_anthropic(lambda r: httpx2.Response(200, json=anthropic_message("refusal", ""))),
    )
    with pytest.raises(ProviderRefusal, match="cyber"):
        provider.complete(REQUEST)


def test_anthropic_status_error_is_wrapped() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            401,
            json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}},
        )

    provider = AnthropicProvider(max_retries=0, timeout_s=10, client=mock_anthropic(handler))
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(REQUEST)
    assert excinfo.value.status_code == 401


def _clear_anthropic_credentials(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "ANTHROPIC_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(home))  # inga sparade profiler
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))


def test_anthropic_no_credentials_at_request_time(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_anthropic_credentials(monkeypatch, tmp_path)
    client = anthropic.Anthropic(
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(500))),
    )
    with pytest.raises(ProviderNotConfigured):
        AnthropicProvider(max_retries=0, timeout_s=10, client=client).complete(REQUEST)


def test_anthropic_missing_profile_at_construction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_anthropic_credentials(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "finns-inte"))
    with pytest.raises(ProviderNotConfigured):
        AnthropicProvider(max_retries=0, timeout_s=10)


def test_openai_request_shape_and_usage() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "c1",
                "object": "chat.completion",
                "created": 0,
                "model": "some-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"echo":"a","confidence":1,"reason":"r"}',
                            "refusal": None,
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 8,
                    "total_tokens": 128,
                    "prompt_tokens_details": {"cached_tokens": 100},
                },
            },
        )

    client = openai.OpenAI(
        api_key="test", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    resp = OpenAIProvider(max_retries=0, timeout_s=10, client=client).complete(REQUEST)

    body = seen["body"]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"]["additionalProperties"] is False
    assert "temperature" not in body
    assert body["messages"][1]["content"][2]["image_url"]["url"].startswith("data:image/png;base64,")
    assert resp.tokens_in == 20 and resp.tokens_cache_read == 100


def test_strict_openai_schema_requires_all_properties() -> None:
    schema = strict_openai_schema({"type": "object", "properties": {"a": {"type": "string", "default": "x"}}})
    assert schema["required"] == ["a"] and schema["additionalProperties"] is False
    assert "default" not in schema["properties"]["a"]
