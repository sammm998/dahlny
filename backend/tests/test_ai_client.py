"""AIClient: validering, retry med felmeddelande, eskalering, cache, kostnadstak och AIRun-loggning.

Inga nätverksanrop – FakeProvider står för svaren. Loggningen går mot riktig Postgres.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.client import AIClient, AITaskFailed, CostCapExceeded, estimate_cost_usd, load_prompt
from app.ai.datatypes import (
    ImagePart,
    ProviderError,
    ProviderNotConfigured,
    ProviderRefusal,
    ProviderResponse,
    TextPart,
)
from app.ai.providers.fake import FakeProvider
from app.ai.schemas.t0 import PingResult
from app.config.settings import ModelsConfig, load_models_config
from app.db.models import AIRun, Project

PRIMARY = "claude-haiku-5-5"
ESCALATION = "claude-sonnet-5-5"
OK = {"echo": "KV01-K1-15", "confidence": 0.99, "reason": "Exakt ekad."}


def make_config(**overrides: object) -> ModelsConfig:
    raw = load_models_config().model_dump()
    raw["tasks"]["T0"] = {"model": PRIMARY, "escalation": [ESCALATION], "effort": "low", "max_tokens": 1024}
    raw.update(overrides)
    return ModelsConfig.model_validate(raw)


def make_client(
    session_factory: sessionmaker[Session], fake: FakeProvider, config: ModelsConfig | None = None
) -> AIClient:
    return AIClient(session_factory, config=config or make_config(), provider_factory=lambda _name: fake)


def runs(session_factory: sessionmaker[Session]) -> list[AIRun]:
    with session_factory() as s:
        return list(s.scalars(select(AIRun).order_by(AIRun.created_at, AIRun.attempt)).all())


def test_success_is_logged_with_tokens_and_cost(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [OK]})
    result = make_client(session_factory, fake).structured("T0", "Kontrollsträng: KV01-K1-15", PingResult)

    assert result == PingResult(**OK)
    [run] = runs(session_factory)
    assert run.status == "ok"
    assert run.step == "T0"
    assert run.model == PRIMARY
    assert run.served_model == PRIMARY
    assert run.prompt_version == "v1"
    assert run.tokens_in == 100 and run.tokens_out == 20
    # Haiku 5.5: 100 in × 0.10 + 20 ut × 0.50 per MTok
    assert run.cost_estimate == Decimal("0.000020")
    assert run.response_json is not None and run.response_json["parsed"] == OK
    assert run.latency_ms is not None


def test_identical_call_is_served_from_cache(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [OK]})
    client = make_client(session_factory, fake)
    first = client.structured("T0", "samma indata", PingResult)
    second = client.structured("T0", "samma indata", PingResult)

    assert first == second
    assert len(fake.calls) == 1, "andra anropet ska inte nå leverantören"
    statuses = [r.status for r in runs(session_factory)]
    assert statuses == ["ok", "cached"]


def test_changed_input_misses_cache(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [OK, OK]})
    client = make_client(session_factory, fake)
    client.structured("T0", "indata A", PingResult)
    client.structured("T0", "indata B", PingResult)
    assert len(fake.calls) == 2


def test_invalid_output_retries_with_error_attached(session_factory: sessionmaker[Session]) -> None:
    bad = {"echo": "x", "confidence": 1.7, "reason": "fel"}  # confidence > 1
    fake = FakeProvider({PRIMARY: [bad, OK]})
    result = make_client(session_factory, fake).structured("T0", "indata", PingResult)

    assert result.confidence == 0.99
    assert [r.status for r in runs(session_factory)] == ["invalid_output", "ok"]
    retry_parts = fake.calls[1].parts
    assert isinstance(retry_parts[-1], TextPart)
    assert "confidence" in retry_parts[-1].text and "underkändes" in retry_parts[-1].text


def test_escalates_after_repeated_invalid_output(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: ["inte json", "{}"], ESCALATION: [OK]})
    result = make_client(session_factory, fake).structured("T0", "indata", PingResult)

    assert result == PingResult(**OK)
    logged = runs(session_factory)
    assert [(r.model, r.status) for r in logged] == [
        (PRIMARY, "invalid_output"),
        (PRIMARY, "invalid_output"),
        (ESCALATION, "ok"),
    ]


def test_refusal_escalates(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [ProviderRefusal("avböjde")], ESCALATION: [OK]})
    make_client(session_factory, fake).structured("T0", "indata", PingResult)
    assert [r.status for r in runs(session_factory)] == ["refused", "ok"]


def test_exhausted_chain_raises_and_everything_is_logged(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: ["x", "x"], ESCALATION: ["x", "x"]})
    with pytest.raises(AITaskFailed) as excinfo:
        make_client(session_factory, fake).structured("T0", "indata", PingResult)
    assert len(excinfo.value.attempts) == 4
    assert all(r.status == "invalid_output" for r in runs(session_factory))


def test_truncated_response_is_not_accepted(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [OK, OK], ESCALATION: [OK, OK]}, stop_reason="max_tokens")
    with pytest.raises(AITaskFailed):
        make_client(session_factory, fake).structured("T0", "indata", PingResult)
    assert {r.status for r in runs(session_factory)} == {"truncated"}


def test_api_error_is_logged_and_raised(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [ProviderError("Anthropic 401: invalid x-api-key", status_code=401)]})
    with pytest.raises(ProviderError):
        make_client(session_factory, fake).structured("T0", "indata", PingResult)
    [run] = runs(session_factory)
    assert run.status == "api_error" and run.error is not None and "401" in run.error


def test_not_configured_provider_is_logged(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [ProviderNotConfigured("ingen nyckel")]})
    with pytest.raises(ProviderNotConfigured):
        make_client(session_factory, fake).structured("T0", "indata", PingResult)
    assert runs(session_factory)[0].status == "not_configured"


def test_images_are_hashed_not_logged(session_factory: sessionmaker[Session]) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    fake = FakeProvider({PRIMARY: [OK]})
    make_client(session_factory, fake).structured(
        "T0", [TextPart("Läs etiketter"), ImagePart(png, label="tile_0_0")], PingResult
    )
    [run] = runs(session_factory)
    image_entry = run.request_json["parts"][1]
    assert image_entry["type"] == "image" and image_entry["bytes"] == len(png)
    assert "data" not in image_entry
    assert len(image_entry["sha256"]) == 64


def test_temperature_only_sent_when_model_supports_it(session_factory: sessionmaker[Session]) -> None:
    config = make_config()
    raw = config.model_dump()
    raw["tasks"]["T0"]["temperature"] = 0.0
    fake = FakeProvider({PRIMARY: [OK]})
    make_client(session_factory, fake, ModelsConfig.model_validate(raw)).structured("T0", "x", PingResult)
    assert fake.calls[0].temperature is None  # Claude-modellerna har supports_temperature: false


def test_cost_cap_blocks_new_calls(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        project = Project(name="Dyr")
        s.add(project)
        s.commit()
        project_id = project.id
    config = make_config(cost_cap_usd_per_project=0.00001)
    fake = FakeProvider({PRIMARY: [OK, OK]})
    client = make_client(session_factory, fake, config)
    client.structured("T0", "första", PingResult, project_id=project_id)  # kostar 0.00002 USD
    with pytest.raises(CostCapExceeded):
        client.structured("T0", "andra", PingResult, project_id=project_id)
    assert len(fake.calls) == 1


def test_prompt_versioning(tmp_path: Path) -> None:
    (tmp_path / "TX").mkdir()
    (tmp_path / "TX" / "v1.md").write_text("ett", encoding="utf-8")
    (tmp_path / "TX" / "v10.md").write_text("tio", encoding="utf-8")
    (tmp_path / "TX" / "v2.md").write_text("två", encoding="utf-8")
    assert load_prompt("TX", prompts_dir=tmp_path).version == "v10"
    assert load_prompt("TX", "v2", prompts_dir=tmp_path).text == "två"


def test_prompt_change_changes_cache_key(session_factory: sessionmaker[Session], tmp_path: Path) -> None:
    (tmp_path / "T0").mkdir()
    prompt = tmp_path / "T0" / "v1.md"
    prompt.write_text("prompt A", encoding="utf-8")
    fake = FakeProvider({PRIMARY: [OK, OK]})
    client = AIClient(
        session_factory, config=make_config(), provider_factory=lambda _n: fake, prompts_dir=tmp_path
    )
    client.structured("T0", "indata", PingResult)
    prompt.write_text("prompt B", encoding="utf-8")
    client.structured("T0", "indata", PingResult)
    assert len(fake.calls) == 2


def test_unknown_price_gives_null_cost() -> None:
    from app.config.settings import ModelInfo

    info = ModelInfo(
        provider="openai",
        input=None,
        output=None,
        cache_read=None,
        cache_write=None,
        supports_temperature=True,
    )
    resp = ProviderResponse(text="{}", served_model="m", stop_reason="stop", tokens_in=10, tokens_out=5)
    assert estimate_cost_usd(info, resp) is None


def test_project_id_is_recorded(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        project = Project(name="P")
        s.add(project)
        s.commit()
        pid: uuid.UUID = project.id
    fake = FakeProvider({PRIMARY: [OK]})
    client = make_client(session_factory, fake)
    client.structured("T0", "x", PingResult, project_id=pid)
    assert runs(session_factory)[0].project_id == pid
    assert client.project_cost_usd(pid) == Decimal("0.000020")


def test_low_confidence_escalates_to_next_model(session_factory: sessionmaker[Session]) -> None:
    unsure = {**OK, "confidence": 0.4}
    fake = FakeProvider({PRIMARY: [unsure], ESCALATION: [OK]})
    result = make_client(session_factory, fake).structured_result(
        "T0", "indata", PingResult, accept=lambda r: r.confidence >= 0.8
    )
    assert result.accepted and result.model == ESCALATION and result.value.confidence == 0.99
    assert [(r.model, r.status) for r in runs(session_factory)] == [
        (PRIMARY, "low_confidence"),
        (ESCALATION, "ok"),
    ]
    assert len(fake.calls) == 2  # ingen omfrågning av samma modell vid låg konfidens


def test_unaccepted_everywhere_returns_flagged_result(session_factory: sessionmaker[Session]) -> None:
    unsure = {**OK, "confidence": 0.4}
    fake = FakeProvider({PRIMARY: [unsure], ESCALATION: [{**unsure, "confidence": 0.5}]})
    result = make_client(session_factory, fake).structured_result(
        "T0", "indata", PingResult, accept=lambda r: r.confidence >= 0.8
    )
    assert not result.accepted and result.value.confidence == 0.5  # sista svaret, flaggat – inte gissat
    assert {r.status for r in runs(session_factory)} == {"low_confidence"}


def test_low_confidence_answers_are_not_served_from_cache(session_factory: sessionmaker[Session]) -> None:
    unsure = {**OK, "confidence": 0.4}
    fake = FakeProvider({PRIMARY: [unsure, OK], ESCALATION: [unsure]})
    client = make_client(session_factory, fake)
    first = client.structured_result("T0", "x", PingResult, accept=lambda r: r.confidence >= 0.8)
    second = client.structured_result("T0", "x", PingResult, accept=lambda r: r.confidence >= 0.8)
    assert not first.accepted and second.accepted and not second.cached


def test_result_carries_run_id(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [OK]})
    result = make_client(session_factory, fake).structured_result("T0", "x", PingResult)
    [run] = runs(session_factory)
    assert result.run_id == run.id and result.served_model == PRIMARY and not result.cached


def test_run_budget_stops_further_calls(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({PRIMARY: [OK, OK]})
    client = AIClient(
        session_factory, config=make_config(), provider_factory=lambda _n: fake, budget_usd=0.00001
    )
    client.structured("T0", "första", PingResult)  # kostar 0.00002 USD
    assert client.spent_usd == Decimal("0.000020")
    with pytest.raises(CostCapExceeded, match="Körningens kostnadstak"):
        client.structured("T0", "andra", PingResult)
    assert len(fake.calls) == 1
