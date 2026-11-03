"""AIClient – det enda stället i systemet som gör AI-anrop (SPEC 7.2, 12).

    client.structured(task_id, inputs, schema) -> instans av schema (Pydantic)

Flöde per anrop:
1. Uppgiften slås upp i models.yaml (modell, eskaleringskedja, effort, max_tokens).
2. Prompt läses från app/ai/prompts/{task_id}/v{n}.md (versionerad).
3. input_hash = sha256 över prompt, indata (bilder som hash), schema och parametrar.
4. Cache: finns en lyckad AIRun med samma (task_id, model, prompt_version, input_hash) för någon
   modell i kedjan återanvänds svaret och en AIRun med status 'cached' loggas.
5. Annars anropas modellerna i kedjans ordning. Ogiltigt svar → ett nytt försök med felet bifogat
   (validation_retries), därefter nästa modell i kedjan. Refusal → nästa modell.
6. Tar kedjan slut kastas AITaskFailed – anroparen flaggar posten för granskning (SPEC 2.7: fail loud).

Varje försök loggas i AIRun i en egen transaktion, så loggen finns kvar även om anroparen rullar tillbaka.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.datatypes import (
    ContentPart,
    ProviderError,
    ProviderNotConfigured,
    ProviderRefusal,
    ProviderRequest,
    ProviderResponse,
    TextPart,
)
from app.ai.providers.base import Provider
from app.config.settings import ModelInfo, ModelsConfig, ProviderName, get_settings, load_models_config
from app.db.models import AIRun

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

ProviderFactory = Callable[[ProviderName], Provider]


class AIError(Exception):
    pass


class AITaskFailed(AIError):
    """Ingen modell i kedjan gav ett giltigt svar. Posten ska flaggas för granskning."""

    def __init__(self, task_id: str, attempts: list[str]) -> None:
        super().__init__(
            f"AI-uppgift {task_id} misslyckades efter {len(attempts)} försök: " + " | ".join(attempts)
        )
        self.task_id = task_id
        self.attempts = attempts


class CostCapExceeded(AIError):
    pass


@dataclass(frozen=True)
class _RunContext:
    """Det som är gemensamt för alla AIRun-rader från ett försök."""

    project_id: uuid.UUID | None
    step: str
    provider: str
    model: str
    prompt_version: str
    input_hash: str
    attempt: int
    request_json: dict[str, Any]


@dataclass(frozen=True)
class AIResult[T: BaseModel]:
    """Svaret och om det godtogs. `accepted=False` betyder: giltigt men under tröskel i alla modeller."""

    value: T
    accepted: bool
    model: str
    served_model: str | None
    run_id: uuid.UUID
    cached: bool = False


@dataclass(frozen=True)
class Prompt:
    task_id: str
    version: str
    text: str


def load_prompt(task_id: str, version: str | None = None, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    task_dir = prompts_dir / task_id
    if version is None:
        candidates = sorted(task_dir.glob("v*.md"), key=lambda p: int(p.stem[1:]))
        if not candidates:
            raise FileNotFoundError(f"Ingen prompt för {task_id} i {task_dir}")
        path = candidates[-1]
    else:
        path = task_dir / f"{version}.md"
    return Prompt(task_id=task_id, version=path.stem, text=path.read_text(encoding="utf-8"))


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_cost_usd(info: ModelInfo, resp: ProviderResponse) -> Decimal | None:
    pairs = [
        (resp.tokens_in, info.input),
        (resp.tokens_out, info.output),
        (resp.tokens_cache_read, info.cache_read),
        (resp.tokens_cache_write, info.cache_write),
    ]
    total = Decimal(0)
    for tokens, price in pairs:
        if not tokens:
            continue
        if price is None:
            return None  # okänt pris → hellre null än fel siffra
        total += Decimal(tokens) * Decimal(str(price)) / Decimal(1_000_000)
    return total.quantize(Decimal("0.000001"))


def default_provider_factory(config: ModelsConfig) -> ProviderFactory:
    cache: dict[ProviderName, Provider] = {}

    def factory(name: ProviderName) -> Provider:
        if name not in cache:
            opts = config.providers.get(name, {})
            retries, timeout = config.defaults.sdk_max_retries, config.defaults.timeout_s
            provider: Provider
            if name == "anthropic":
                from app.ai.providers.anthropic_provider import AnthropicProvider

                settings = get_settings()
                key = settings.anthropic_api_key
                provider = AnthropicProvider(
                    max_retries=retries,
                    timeout_s=timeout,
                    server_side_fallback=bool(opts.get("server_side_fallback")),
                    api_key=key.get_secret_value() if key is not None else None,
                    base_url=settings.anthropic_base_url,
                )
            elif name == "openai":
                from app.ai.providers.openai_provider import OpenAIProvider

                provider = OpenAIProvider(max_retries=retries, timeout_s=timeout)
            elif name == "google":
                from app.ai.providers.google_provider import GoogleProvider

                provider = GoogleProvider()
            else:
                raise ProviderNotConfigured(f"Leverantören {name!r} saknar adapter")
            cache[name] = provider
        return cache[name]

    return factory


class AIClient:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        config: ModelsConfig | None = None,
        provider_factory: ProviderFactory | None = None,
        prompts_dir: Path = PROMPTS_DIR,
        use_cache: bool = True,
        budget_usd: float | None = None,
    ) -> None:
        """budget_usd: tak för vad den här klienten får kosta totalt (t.ex. en mätkörning utan projekt).
        Nås det kastas CostCapExceeded före nästa anrop – det redan gjorda står kvar i ai_run."""
        self._budget = Decimal(str(budget_usd)) if budget_usd is not None else None
        self.spent_usd = Decimal(0)
        self._spent_lock = threading.Lock()  # AIClient används från flera trådar (T5)
        self._scope_limit: Decimal | None = None
        self._scope_name = ""
        self._sessions = session_factory
        self._config = config or load_models_config()
        self._providers = provider_factory or default_provider_factory(self._config)
        self._prompts_dir = prompts_dir
        self._use_cache = use_cache

    # ------------------------------------------------------------------ public API

    @property
    def config(self) -> ModelsConfig:
        return self._config

    @contextmanager
    def budget_scope(self, usd: float | None, name: str) -> Iterator[None]:
        """Tak för en del av körningen, t.ex. ett ritningsblad: högst `usd` till inom blocket (utöver
        körningens och projektets tak). Nås det kastas CostCapExceeded före nästa anrop."""
        prev = (self._scope_limit, self._scope_name)
        self._scope_limit = None if usd is None else self.spent_usd + Decimal(str(usd))
        self._scope_name = name
        try:
            yield
        finally:
            self._scope_limit, self._scope_name = prev

    def structured[T: BaseModel](
        self,
        task_id: str,
        inputs: str | Sequence[ContentPart],
        schema: type[T],
        *,
        project_id: uuid.UUID | None = None,
        context_blocks: Sequence[str] = (),
    ) -> T:
        """Ett validerat svar, eller AITaskFailed. Se structured_result för konfidensstyrd eskalering."""
        result = self.structured_result(
            task_id, inputs, schema, project_id=project_id, context_blocks=context_blocks
        )
        return result.value

    def structured_result[T: BaseModel](
        self,
        task_id: str,
        inputs: str | Sequence[ContentPart],
        schema: type[T],
        *,
        project_id: uuid.UUID | None = None,
        context_blocks: Sequence[str] = (),
        accept: Callable[[T], bool] | None = None,
    ) -> AIResult[T]:
        """Som structured, men med `accept`: ett giltigt svar som inte godtas (t.ex. för låg konfidens) loggas
        som 'low_confidence' och nästa modell i kedjan tillfrågas (SPEC 7.1). Godtar ingen modell returneras
        det sista giltiga svaret med accepted=False – anroparen flaggar för granskning, gissar inte."""
        task = self._config.task(task_id)
        prompt = load_prompt(task_id, task.prompt_version, self._prompts_dir)
        parts: tuple[ContentPart, ...] = (TextPart(inputs),) if isinstance(inputs, str) else tuple(inputs)
        json_schema = schema.model_json_schema()
        max_tokens = task.max_tokens or self._config.defaults.max_tokens

        input_hash = _sha256(
            _canonical(
                {
                    "system": prompt.text,
                    "context": list(context_blocks),
                    "parts": [p.fingerprint() for p in parts],
                    "schema": json_schema,
                    "params": {
                        "max_tokens": max_tokens,
                        "effort": task.effort,
                        "temperature": task.temperature,
                    },
                }
            )
        )
        chain = task.model_chain()

        if self._use_cache:
            hit = self._cached(task_id, chain, prompt.version, input_hash, schema)
            if hit is not None:
                run, value = hit
                ctx = _RunContext(
                    project_id=project_id, step=task_id, provider=run.provider, model=run.model,
                    prompt_version=prompt.version, input_hash=input_hash, attempt=0,
                    request_json={"cache_hit_of": str(run.id)},
                )  # fmt: skip
                run_id = self._log(
                    ctx, "cached", served_model=run.served_model, response_json=run.response_json,
                    cost=Decimal(0), latency_ms=0,
                )  # fmt: skip
                return AIResult(value, True, run.model, run.served_model, run_id, cached=True)

        failures: list[str] = []
        unaccepted: AIResult[T] | None = None
        for model in chain:
            info = self._config.models[model]
            temperature = task.temperature if info.supports_temperature else None
            feedback: str | None = None
            for attempt in range(1, self._config.defaults.validation_retries + 2):
                self._check_cost_cap(project_id)
                req_parts = parts if feedback is None else (*parts, TextPart(feedback))
                request = ProviderRequest(
                    model=model, system=prompt.text, context_blocks=tuple(context_blocks), parts=req_parts,
                    json_schema=json_schema, schema_name=schema.__name__, max_tokens=max_tokens,
                    effort=task.effort, temperature=temperature,
                )  # fmt: skip
                ctx = _RunContext(
                    project_id=project_id, step=task_id, provider=info.provider, model=model,
                    prompt_version=prompt.version, input_hash=input_hash, attempt=attempt,
                    request_json=self._request_log(request),
                )  # fmt: skip
                started = time.monotonic()
                try:
                    resp = self._providers(info.provider).complete(request)
                except ProviderNotConfigured as exc:
                    self._log(ctx, "not_configured", error=str(exc), latency_ms=_ms(started))
                    raise
                except ProviderRefusal as exc:
                    self._log(
                        ctx, "refused", error=str(exc), served_model=exc.served_model,
                        response_json=exc.raw, latency_ms=_ms(started),
                    )  # fmt: skip
                    failures.append(f"{model}: refusal")
                    break  # nästa modell i kedjan
                except ProviderError as exc:
                    self._log(ctx, "api_error", error=str(exc), latency_ms=_ms(started))
                    raise
                latency = _ms(started)
                cost = estimate_cost_usd(info, resp)
                response_json: dict[str, Any] = {"text": resp.text, "raw": resp.raw}
                if resp.stop_reason == "max_tokens":
                    error = f"Svaret kapades vid max_tokens={max_tokens}"
                    self._log(
                        ctx, "truncated", resp=resp, cost=cost, latency_ms=latency,
                        response_json=response_json, error=error,
                    )  # fmt: skip
                    failures.append(f"{model}#{attempt}: truncated")
                    feedback = None
                    continue
                try:
                    value = schema.model_validate_json(resp.text)
                except ValidationError as exc:
                    error = _short_validation_error(exc)
                    self._log(
                        ctx, "invalid_output", resp=resp, cost=cost, latency_ms=latency,
                        response_json=response_json, error=error,
                    )  # fmt: skip
                    failures.append(f"{model}#{attempt}: invalid")
                    feedback = (
                        "Föregående svar underkändes av valideringen:\n"
                        f"{error}\n"
                        "Returnera ett nytt svar som följer schemat exakt. "
                        "Hitta inte på värden; okänt = null."
                    )
                    continue
                response_json["parsed"] = value.model_dump(mode="json")
                if accept is not None and not accept(value):
                    run_id = self._log(
                        ctx, "low_confidence", resp=resp, cost=cost, latency_ms=latency,
                        response_json=response_json, error="Giltigt svar men under uppgiftens tröskel",
                    )  # fmt: skip
                    failures.append(f"{model}#{attempt}: low_confidence")
                    unaccepted = AIResult(value, False, model, resp.served_model, run_id)
                    break  # samma modell igen ger samma svar – nästa modell i kedjan
                run_id = self._log(
                    ctx, "ok", resp=resp, cost=cost, latency_ms=latency, response_json=response_json
                )
                return AIResult(value, True, model, resp.served_model, run_id)
        if unaccepted is not None:
            return unaccepted
        raise AITaskFailed(task_id, failures)

    def project_cost_usd(self, project_id: uuid.UUID) -> Decimal:
        with self._sessions() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(AIRun.cost_estimate), 0)).where(AIRun.project_id == project_id)
            )
        return Decimal(total or 0)

    # ------------------------------------------------------------------ internals

    @staticmethod
    def cache_key(task_id: str, model: str, prompt_version: str, input_hash: str) -> str:
        return _sha256(f"{task_id}|{model}|{prompt_version}|{input_hash}")

    def _cached[T: BaseModel](
        self, task_id: str, chain: list[str], prompt_version: str, input_hash: str, schema: type[T]
    ) -> tuple[AIRun, T] | None:
        keys = [self.cache_key(task_id, m, prompt_version, input_hash) for m in chain]
        with self._sessions() as session:
            runs = session.scalars(
                select(AIRun)
                .where(AIRun.cache_key.in_(keys), AIRun.status == "ok")
                .order_by(AIRun.created_at.desc())
            ).all()
        by_key = {r.cache_key: r for r in reversed(runs)}  # nyaste vinner
        for key in keys:  # kedjans ordning: primärmodellens svar först
            run = by_key.get(key)
            if run is None or not run.response_json or "parsed" not in run.response_json:
                continue
            try:
                return run, schema.model_validate(run.response_json["parsed"])
            except ValidationError:
                continue  # schemat har ändrats sedan dess – anropa på nytt
        return None

    def _check_cost_cap(self, project_id: uuid.UUID | None) -> None:
        if self._scope_limit is not None and self.spent_usd >= self._scope_limit:
            raise CostCapExceeded(
                f"Kostnadstaket för {self._scope_name} är nått ({self.spent_usd} USD totalt)."
            )
        if self._budget is not None and self.spent_usd >= self._budget:
            raise CostCapExceeded(
                f"Körningens kostnadstak {self._budget} USD är nått ({self.spent_usd} USD). "
                "Pausar – fråga användaren."
            )
        if project_id is None:
            return
        cap = Decimal(str(self._config.cost_cap_usd_per_project))
        spent = self.project_cost_usd(project_id)
        if spent >= cap:
            raise CostCapExceeded(
                f"Kostnadstaket {cap} USD för projektet är nått ({spent} USD). Pausar – fråga användaren."
            )

    @staticmethod
    def _request_log(request: ProviderRequest) -> dict[str, Any]:
        return {
            "model": request.model,
            "system_sha256": _sha256(request.system),
            "context_blocks_sha256": [_sha256(b) for b in request.context_blocks],
            "parts": [p.fingerprint() for p in request.parts],
            "schema_name": request.schema_name,
            "max_tokens": request.max_tokens,
            "effort": request.effort,
            "temperature": request.temperature,
        }

    def _log(
        self,
        ctx: _RunContext,
        status: str,
        *,
        resp: ProviderResponse | None = None,
        served_model: str | None = None,
        response_json: dict[str, Any] | None = None,
        cost: Decimal | None = None,
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> uuid.UUID:
        run = AIRun(
            id=uuid.uuid4(),
            project_id=ctx.project_id,
            step=ctx.step,
            provider=ctx.provider,
            model=ctx.model,
            served_model=resp.served_model if resp else served_model,
            prompt_version=ctx.prompt_version,
            input_hash=ctx.input_hash,
            cache_key=self.cache_key(ctx.step, ctx.model, ctx.prompt_version, ctx.input_hash),
            attempt=ctx.attempt,
            request_json=ctx.request_json,
            response_json=response_json,
            stop_reason=resp.stop_reason if resp else None,
            tokens_in=resp.tokens_in if resp else None,
            tokens_out=resp.tokens_out if resp else None,
            tokens_cache_read=resp.tokens_cache_read if resp else None,
            tokens_cache_write=resp.tokens_cache_write if resp else None,
            cost_estimate=cost,
            latency_ms=latency_ms,
            status=status,
            error=error,
            finished_at=datetime.now(UTC),
        )
        with self._sessions() as session:
            session.add(run)
            session.commit()
        if cost is not None:
            with self._spent_lock:
                self.spent_usd += cost
        return run.id


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _short_validation_error(exc: ValidationError, limit: int = 20) -> str:
    lines = [f"- {'.'.join(str(p) for p in e['loc']) or '(rot)'}: {e['msg']}" for e in exc.errors()[:limit]]
    return "\n".join(lines)
