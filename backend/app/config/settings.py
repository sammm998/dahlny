"""Miljöinställningar och typad inläsning av config-filerna i app/config/.

Allt som är tröskelvärden, modellval eller grammatik ligger i YAML (SPEC 2.6, 12) och valideras här
med Pydantic så att en felskriven config fallerar högljutt vid start i stället för mitt i en körning.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent

ProviderName = Literal["anthropic", "openai", "google", "fake"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://vskalkyl:vskalkyl@localhost:5432/vskalkyl"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "vs-kalkyl"
    ai_provider: ProviderName = "anthropic"
    # Anthropic-nyckeln: DAHLNY_ANTHROPIC_API_KEY i första hand. ANTHROPIC_API_KEY är reserverad av Claude
    # Code i molnmiljön och når inte sessionen där; den används bara som reserv (t.ex. på en egen dator).
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("DAHLNY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    )
    # Adressen sätts uttryckligen: SDK:n läser annars ANTHROPIC_BASE_URL, som i molnmiljön pekar på Claude
    # Codes egen tjänst – nyckeln ska aldrig skickas dit.
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com", validation_alias=AliasChoices("DAHLNY_ANTHROPIC_BASE_URL")
    )
    config_dir: Path = CONFIG_DIR
    storage_dir: Path = Path("storage")  # lokal fillagring (originalfiler, renderingar); S3/MinIO senare


@lru_cache
def get_settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------- models.yaml


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelDefaults(_Strict):
    max_tokens: int = Field(gt=0)
    sdk_max_retries: int = Field(ge=0)
    timeout_s: float = Field(gt=0)
    validation_retries: int = Field(ge=0)
    max_concurrency: int = Field(ge=1)


class ModelInfo(_Strict):
    provider: ProviderName
    input: float | None
    output: float | None
    cache_read: float | None
    cache_write: float | None
    supports_temperature: bool


class TaskConfig(_Strict):
    model: str
    escalation: list[str] = Field(default_factory=list)
    effort: Effort | None = None
    max_tokens: int | None = None
    temperature: float | None = None  # skickas bara till modeller med supports_temperature
    prompt_version: str | None = None  # None = senaste app/ai/prompts/{task}/v{n}.md
    description: str = ""

    def model_chain(self) -> list[str]:
        return [self.model, *self.escalation]


class ModelsConfig(_Strict):
    version: int
    defaults: ModelDefaults
    cost_cap_usd_per_project: float = Field(gt=0)
    labels_budget_usd_per_sheet: float = Field(gt=0)
    labels_routing: Literal["all", "tiles", "labels"]
    providers: dict[ProviderName, dict[str, Any]]
    models: dict[str, ModelInfo]
    tasks: dict[str, TaskConfig]

    @model_validator(mode="after")
    def _every_task_model_is_known(self) -> ModelsConfig:
        for task_id, task in self.tasks.items():
            for model in task.model_chain():
                if model not in self.models:
                    raise ValueError(f"Uppgift {task_id}: modellen {model!r} saknas under 'models'")
        return self

    def task(self, task_id: str) -> TaskConfig:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"Okänd AI-uppgift {task_id!r} – lägg till den i models.yaml") from exc


# --------------------------------------------------------------------------- label_grammar.yaml


class PatternWithExamples(_Strict):
    pattern: str
    examples_ok: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class HeightPatterns(_Strict):
    cl: str
    vg: str


class LabelGrammar(_Strict):
    pipe: PatternWithExamples
    height: HeightPatterns
    slope: str
    object: PatternWithExamples
    schematic_valve: PatternWithExamples
    alternatives: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _patterns_compile(self) -> LabelGrammar:
        for pattern in self.all_patterns().values():
            re.compile(pattern)
        return self

    def all_patterns(self) -> dict[str, str]:
        patterns = {
            "pipe": self.pipe.pattern,
            "height.cl": self.height.cl,
            "height.vg": self.height.vg,
            "slope": self.slope,
            "object": self.object.pattern,
            "schematic_valve": self.schematic_valve.pattern,
        }
        patterns.update({f"alternatives[{i}]": p for i, p in enumerate(self.alternatives)})
        return patterns


# --------------------------------------------------------------------------- reference_tables.yaml


class AmaRef(_Strict):
    code: str
    title: str


class ReferenceTables(_Strict):
    materials: dict[str, str]
    systems: dict[str, str]
    material_ama: dict[str, AmaRef]


# --------------------------------------------------------------------------- thresholds.yaml


class Thresholds(BaseModel):
    """Trösklar läses som nästlade sektioner; `get("assign.leader_confidence")` fallerar vid okänd nyckel."""

    model_config = ConfigDict(extra="allow", frozen=True)

    def get(self, dotted: str) -> float:
        node: Any = self.model_dump()
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"Tröskel {dotted!r} saknas i thresholds.yaml")
            node = node[part]
        if isinstance(node, bool) or not isinstance(node, int | float):
            raise TypeError(f"Tröskel {dotted!r} är inte ett tal")
        return float(node)


# --------------------------------------------------------------------------- documents.yaml


class DrawingNumberConfig(_Strict):
    patterns: list[str]
    examples_ok: list[str] = Field(default_factory=list)


class ScaleConfig(_Strict):
    ratio: str
    none_markers: list[str]


class PageKindRule(_Strict):
    kind: Literal["tb", "drawing_list", "plan", "schematic", "section", "detail", "legend_only", "other"]
    any_text: list[str] = Field(default_factory=list)
    all_text: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _has_condition(self) -> PageKindRule:
        if not self.any_text and not self.all_text:
            raise ValueError(f"Regel för {self.kind} saknar villkor")
        return self


class DrawingListConfig(_Strict):
    columns: dict[str, list[str]]
    row_tolerance_fraction: float = Field(gt=0, le=2)
    table_end_gap_factor: float = Field(gt=1)


class TitleBlockConfig(_Strict):
    regions: list[tuple[float, float, float, float]]
    dpi: int = Field(gt=0)


class DocumentsConfig(_Strict):
    drawing_number: DrawingNumberConfig
    scale: ScaleConfig
    project_no: str
    date: str
    paper_sizes_mm: dict[str, tuple[float, float]]
    paper_size_tolerance_mm: float
    page_kind_rules: list[PageKindRule]
    drawing_list: DrawingListConfig
    title_block: TitleBlockConfig
    purpose_markers: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _patterns_compile(self) -> DocumentsConfig:
        for pattern in [*self.drawing_number.patterns, self.scale.ratio, self.project_no, self.date]:
            re.compile(pattern)
        return self


# --------------------------------------------------------------------------- drawings.yaml


class VvsEngineConfig(_Strict):
    command: list[str]
    timeout_s: float = Field(gt=0)
    supported_artifact_schemas: list[int]
    confidence_tiers: dict[str, float]
    unknown_tier_confidence: float = Field(ge=0, le=1)
    confirmed_states: list[str]
    verified_scale_states: list[str]
    # motorns inställbara regel-id → nyckel i thresholds.yaml (ett värde, en källa: VS-Kalkyls trösklar)
    rules_from_thresholds: dict[str, str] = Field(default_factory=dict)
    rules_from_thresholds_mm_to_pt: dict[str, list[str]] = Field(default_factory=dict)


class DrawingsConfig(_Strict):
    vvs_engine: VvsEngineConfig


class RulesConfig(_Strict):
    option_phrases: list[str]
    placeholder_patterns: list[str]
    decide_phrases: list[str]
    decide_selection_words: list[str]
    spec_labels: list[str]
    spec_label_reach_chars: int


# --------------------------------------------------------------------------- loaders


def _load_yaml(name: str, config_dir: Path | None = None) -> Any:
    path = (config_dir or get_settings().config_dir) / name
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache
def load_models_config() -> ModelsConfig:
    return ModelsConfig.model_validate(_load_yaml("models.yaml"))


@lru_cache
def load_label_grammar() -> LabelGrammar:
    return LabelGrammar.model_validate(_load_yaml("label_grammar.yaml"))


@lru_cache
def load_reference_tables() -> ReferenceTables:
    return ReferenceTables.model_validate(_load_yaml("reference_tables.yaml"))


@lru_cache
def load_documents_config() -> DocumentsConfig:
    return DocumentsConfig.model_validate(_load_yaml("documents.yaml"))


@lru_cache
def load_drawings_config() -> DrawingsConfig:
    return DrawingsConfig.model_validate(_load_yaml("drawings.yaml"))


@lru_cache
def load_thresholds() -> Thresholds:
    return Thresholds.model_validate(_load_yaml("thresholds.yaml"))


@lru_cache
def load_rules_config() -> RulesConfig:
    return RulesConfig.model_validate(_load_yaml("rules.yaml"))


class ArticleMatchConfig(_Strict):
    rsk_score: float
    art_no_score: float
    stock_min_score: float
    request_below_score: float
    fuzzy_candidates: int
    fuzzy_min_similarity: float


class ArticlesConfig(_Strict):
    columns: dict[str, list[str]]
    required: list[str]
    stock_values: dict[str, list[str]]
    match: ArticleMatchConfig
    accessories: dict[str, list[str]]
    accessory_context: list[str]


class PrixelColumn(_Strict):
    key: str
    title: str


class PrixelConfig(_Strict):
    columns: list[PrixelColumn]
    decimal_comma: bool
    unit_map: dict[str, str]
    description_keywords: list[str]
    description_max_lines: int


@lru_cache
def load_articles_config() -> ArticlesConfig:
    return ArticlesConfig.model_validate(_load_yaml("articles.yaml"))


@lru_cache
def load_prixel_config() -> PrixelConfig:
    return PrixelConfig.model_validate(_load_yaml("prixel.yaml"))
