"""SQLAlchemy-modeller enligt SPEC kapitel 5.

Koordinater lagras i PDF-punkter i sidans koordinatsystem (origo uppe vänster, som PyMuPDF) plus
page_no; verkliga mått i meter efter skalning. Geometrier ligger i PostGIS utan SRID (kartesiskt
sidplan i PDF-punkter) så att närhetsfrågor kan göras i databasen.

Avsteg/tillägg mot SPEC 5 (motiverade):
- Document.format och Page.format har även `pdf_mixed` och `image` (SPEC 6.1.2 bestämmer format per sida).
- Page.kind har `legend_only` (SPEC 6.1.4).
- ProjectRule finns som egen tabell (SPEC 6.2.7, Bilaga A.2).
- AIRun har extra fält för cache-nyckel, faktiskt svarande modell, cache-tokens och fel (SPEC 2.4, 7.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampedUUID, enum_column

DOCUMENT_KINDS = ("tb", "drawing_list", "plan", "schematic", "section", "detail", "other")
PAGE_KINDS = (*DOCUMENT_KINDS, "legend_only")
FORMATS = ("pdf_vector", "pdf_raster", "pdf_mixed", "image", "dwg", "dxf", "ifc")


def _fk(table: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[Any]:
    return mapped_column(
        UUID(as_uuid=True), sa.ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable, index=True
    )


def _source_refs() -> Mapped[list[Any]]:
    # [{document_id, page, bbox, method, model, confidence}] – SPEC 2.3
    return mapped_column(nullable=False, server_default=sa.text("'[]'::jsonb"))


class Project(TimestampedUUID, Base):
    __tablename__ = "project"
    name: Mapped[str] = mapped_column(sa.String(300))
    customer: Mapped[str | None] = mapped_column(sa.String(300))
    consultant: Mapped[str | None] = mapped_column(sa.String(300))
    project_no: Mapped[str | None] = mapped_column(sa.String(100))
    status: Mapped[str] = mapped_column(sa.String(50), server_default="new")
    created_by: Mapped[str | None] = mapped_column(sa.String(200))


class Document(TimestampedUUID, Base):
    __tablename__ = "document"
    __table_args__ = (sa.UniqueConstraint("project_id", "sha256", name="uq_document_project_sha256"),)
    project_id: Mapped[uuid.UUID] = _fk("project")
    filename: Mapped[str] = mapped_column(sa.String(500))
    kind: Mapped[str | None] = mapped_column(enum_column("document_kind", *DOCUMENT_KINDS))
    format: Mapped[str] = mapped_column(enum_column("document_format", *FORMATS))
    sha256: Mapped[str] = mapped_column(sa.String(64))
    pages: Mapped[int] = mapped_column(sa.Integer, server_default="0")


class Page(TimestampedUUID, Base):
    __tablename__ = "page"
    __table_args__ = (sa.UniqueConstraint("document_id", "page_no", name="uq_page_document_page_no"),)
    document_id: Mapped[uuid.UUID] = _fk("document")
    page_no: Mapped[int] = mapped_column(sa.Integer)
    width_pt: Mapped[float] = mapped_column(sa.Float)
    height_pt: Mapped[float] = mapped_column(sa.Float)
    kind: Mapped[str | None] = mapped_column(enum_column("page_kind", *PAGE_KINDS))
    format: Mapped[str | None] = mapped_column(enum_column("page_format", *FORMATS))
    title_block_json: Mapped[dict[str, Any] | None]
    drawing_no: Mapped[str | None] = mapped_column(sa.String(100))
    level_name: Mapped[str | None] = mapped_column(sa.String(200))
    scale_declared: Mapped[str | None] = mapped_column(sa.String(100))
    paper_size_declared: Mapped[str | None] = mapped_column(sa.String(20))
    scale_effective_m_per_pt: Mapped[float | None] = mapped_column(sa.Float)
    scale_confidence: Mapped[float | None] = mapped_column(sa.Float)
    scale_method: Mapped[str | None] = mapped_column(sa.String(50))


class StyleProfile(TimestampedUUID, Base):
    __tablename__ = "style_profile"
    __table_args__ = (
        sa.UniqueConstraint("consultant", "version", name="uq_style_profile_consultant_version"),
    )
    consultant: Mapped[str] = mapped_column(sa.String(300))
    label_regex_json: Mapped[dict[str, Any] | None]
    layer_map_json: Mapped[dict[str, Any] | None]
    line_width_map_json: Mapped[dict[str, Any] | None]
    legend_overrides_json: Mapped[dict[str, Any] | None]
    examples_json: Mapped[list[Any] | None]
    version: Mapped[int] = mapped_column(sa.Integer, server_default="1")


class Legend(TimestampedUUID, Base):
    __tablename__ = "legend"
    project_id: Mapped[uuid.UUID] = _fk("project")
    page_id: Mapped[uuid.UUID | None] = _fk("page", nullable=True, ondelete="SET NULL")
    materials_json: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))
    systems_json: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))
    notes_json: Mapped[dict[str, Any]] = mapped_column(server_default=sa.text("'{}'::jsonb"))


class SpecItem(TimestampedUUID, Base):
    __tablename__ = "spec_item"
    project_id: Mapped[uuid.UUID] = _fk("project")
    ama_code: Mapped[str | None] = mapped_column(sa.String(30))
    ama_title: Mapped[str | None] = mapped_column(sa.String(300))
    designation: Mapped[str | None] = mapped_column(sa.String(100), index=True)
    description: Mapped[str | None] = mapped_column(sa.Text)
    manufacturer: Mapped[str | None] = mapped_column(sa.String(200))
    model: Mapped[str | None] = mapped_column(sa.String(200))
    article_no: Mapped[str | None] = mapped_column(sa.String(100))
    rsk: Mapped[str | None] = mapped_column(sa.String(20), index=True)
    quantity: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(sa.String(20))
    quantity_mode: Mapped[str] = mapped_column(
        enum_column("quantity_mode", "fixed", "per_drawing", "range", "regulated")
    )
    quantity_range: Mapped[dict[str, Any] | None]  # {"min": 1, "max": 2}
    requirements_text: Mapped[str | None] = mapped_column(sa.Text)
    parent_item_id: Mapped[uuid.UUID | None] = _fk("spec_item", nullable=True)
    source_refs: Mapped[list[Any]] = _source_refs()


class ProjectRule(TimestampedUUID, Base):
    """Generella krav ur TB (SPEC 6.2.7), t.ex. 'Blandare utan föravstängning förses med Ballofix'."""

    __tablename__ = "project_rule"
    project_id: Mapped[uuid.UUID] = _fk("project")
    category: Mapped[str] = mapped_column(sa.String(50))
    text: Mapped[str] = mapped_column(sa.Text)
    applies_to_json: Mapped[dict[str, Any] | None]
    source_refs: Mapped[list[Any]] = _source_refs()


class Label(TimestampedUUID, Base):
    __tablename__ = "label"
    page_id: Mapped[uuid.UUID] = _fk("page")
    raw_text: Mapped[str] = mapped_column(sa.String(300))
    bbox: Mapped[Any] = mapped_column(Geometry("POLYGON", spatial_index=True))
    rotation: Mapped[float] = mapped_column(sa.Float, server_default="0")
    read_method: Mapped[str] = mapped_column(enum_column("read_method", "text_layer", "vision", "ocr"))
    read_confidence: Mapped[float] = mapped_column(sa.Float)
    parsed_json: Mapped[dict[str, Any] | None]
    parse_status: Mapped[str] = mapped_column(enum_column("parse_status", "ok", "unknown_token", "failed"))


class PipeSegment(TimestampedUUID, Base):
    __tablename__ = "pipe_segment"
    page_id: Mapped[uuid.UUID] = _fk("page")
    geom: Mapped[Any] = mapped_column(Geometry("LINESTRING", spatial_index=True))
    length_pt: Mapped[float] = mapped_column(sa.Float)
    length_m: Mapped[float | None] = mapped_column(sa.Float)
    stroke_width: Mapped[float | None] = mapped_column(sa.Float)
    dash_pattern: Mapped[str | None] = mapped_column(sa.String(100))
    color: Mapped[str | None] = mapped_column(sa.String(30))
    layer: Mapped[str | None] = mapped_column(sa.String(200))
    assigned_label_id: Mapped[uuid.UUID | None] = _fk("label", nullable=True, ondelete="SET NULL")
    system: Mapped[str | None] = mapped_column(sa.String(30))
    material: Mapped[str | None] = mapped_column(sa.String(30))
    dim: Mapped[str | None] = mapped_column(sa.String(30))
    assign_method: Mapped[str | None] = mapped_column(sa.String(30))
    assign_confidence: Mapped[float | None] = mapped_column(sa.Float)
    is_vertical_symbol: Mapped[bool] = mapped_column(sa.Boolean, server_default=sa.false())
    z_from_m: Mapped[float | None] = mapped_column(sa.Float)
    z_to_m: Mapped[float | None] = mapped_column(sa.Float)


class PipeRun(TimestampedUUID, Base):
    __tablename__ = "pipe_run"
    project_id: Mapped[uuid.UUID] = _fk("project")
    system: Mapped[str] = mapped_column(sa.String(30))
    material: Mapped[str | None] = mapped_column(sa.String(30))
    dim: Mapped[str | None] = mapped_column(sa.String(30))
    length_m_horizontal: Mapped[float] = mapped_column(sa.Float, server_default="0")
    length_m_vertical: Mapped[float | None] = mapped_column(sa.Float)  # None = "ej bestämd" (6.4.3 j)
    length_m_total: Mapped[float | None] = mapped_column(sa.Float)
    segment_ids: Mapped[list[Any]] = mapped_column(server_default=sa.text("'[]'::jsonb"))
    confidence: Mapped[float] = mapped_column(sa.Float)


class Symbol(TimestampedUUID, Base):
    __tablename__ = "symbol"
    page_id: Mapped[uuid.UUID] = _fk("page")
    kind: Mapped[str] = mapped_column(sa.String(50))  # floor_drain|valve|backflow|strainer|cleanout|...
    tag: Mapped[str | None] = mapped_column(sa.String(100))
    bbox: Mapped[Any] = mapped_column(Geometry("POLYGON", spatial_index=True))
    read_method: Mapped[str] = mapped_column(sa.String(30))
    confidence: Mapped[float] = mapped_column(sa.Float)
    linked_spec_item_id: Mapped[uuid.UUID | None] = _fk("spec_item", nullable=True, ondelete="SET NULL")


class QuantityLine(TimestampedUUID, Base):
    __tablename__ = "quantity_line"
    project_id: Mapped[uuid.UUID] = _fk("project")
    spec_item_id: Mapped[uuid.UUID | None] = _fk("spec_item", nullable=True, ondelete="SET NULL")
    source: Mapped[str] = mapped_column(enum_column("quantity_source", "tb", "drawing", "merged"))
    designation: Mapped[str | None] = mapped_column(sa.String(100))
    description: Mapped[str | None] = mapped_column(sa.Text)
    quantity: Mapped[Decimal | None] = mapped_column(sa.Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(sa.String(20))
    confidence: Mapped[float] = mapped_column(sa.Float)
    status: Mapped[str] = mapped_column(
        enum_column("quantity_status", "auto", "review", "approved"), server_default="review"
    )


class Deviation(TimestampedUUID, Base):
    __tablename__ = "deviation"
    project_id: Mapped[uuid.UUID] = _fk("project")
    rule_id: Mapped[str] = mapped_column(sa.String(60), index=True)
    severity: Mapped[str] = mapped_column(enum_column("severity", "info", "warning", "critical"))
    message: Mapped[str] = mapped_column(sa.Text)
    refs: Mapped[list[Any]] = mapped_column(server_default=sa.text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(
        enum_column("deviation_status", "open", "resolved", "ignored"), server_default="open"
    )
    note: Mapped[str | None] = mapped_column(sa.Text)
    question: Mapped[str | None] = mapped_column(
        sa.Text
    )  # föreslagen fråga till konsult/beställare (SPEC 6.5)


class Article(TimestampedUUID, Base):
    __tablename__ = "article"
    __table_args__ = (
        sa.Index(
            "ix_article_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}
        ),
        sa.Index(
            "ix_article_supplier_art_no_trgm",
            "supplier_art_no",
            postgresql_using="gin",
            postgresql_ops={"supplier_art_no": "gin_trgm_ops"},
        ),
    )
    dahl_art_no: Mapped[str] = mapped_column(sa.String(50), unique=True)
    rsk: Mapped[str | None] = mapped_column(sa.String(20), index=True)
    supplier: Mapped[str | None] = mapped_column(sa.String(200))
    supplier_art_no: Mapped[str | None] = mapped_column(sa.String(100))
    name: Mapped[str] = mapped_column(sa.String(500))
    stock_status: Mapped[str] = mapped_column(enum_column("stock_status", "stock", "virtual", "order"))
    unit: Mapped[str | None] = mapped_column(sa.String(20))
    discount_group: Mapped[str | None] = mapped_column(sa.String(50))
    attributes_json: Mapped[dict[str, Any] | None]


class ArticleMatch(TimestampedUUID, Base):
    __tablename__ = "article_match"
    quantity_line_id: Mapped[uuid.UUID] = _fk("quantity_line")
    article_id: Mapped[uuid.UUID | None] = _fk("article", nullable=True, ondelete="SET NULL")
    method: Mapped[str] = mapped_column(enum_column("match_method", "rsk", "art_no", "fuzzy", "ai"))
    score: Mapped[float] = mapped_column(sa.Float)
    outcome: Mapped[str] = mapped_column(
        enum_column("match_outcome", "stock", "virtual", "request", "uncertain")
    )
    approved_by: Mapped[str | None] = mapped_column(sa.String(200))


class SupplierRequest(TimestampedUUID, Base):
    __tablename__ = "supplier_request"
    project_id: Mapped[uuid.UUID] = _fk("project")
    supplier: Mapped[str] = mapped_column(sa.String(200))
    line_ids: Mapped[list[Any]] = mapped_column(server_default=sa.text("'[]'::jsonb"))
    subject: Mapped[str] = mapped_column(sa.String(500))
    body_md: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(
        enum_column("supplier_request_status", "draft", "approved", "sent", "answered"),
        server_default="draft",
    )
    reply_prices_json: Mapped[dict[str, Any] | None]


class Correction(TimestampedUUID, Base):
    __tablename__ = "correction"
    project_id: Mapped[uuid.UUID] = _fk("project")
    entity: Mapped[str] = mapped_column(sa.String(60))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    field: Mapped[str] = mapped_column(sa.String(100))
    old: Mapped[dict[str, Any] | None]
    new: Mapped[dict[str, Any] | None]
    user: Mapped[str] = mapped_column(sa.String(200))


class AIRun(TimestampedUUID, Base):
    """Varje AI-anrop – lyckat, misslyckat eller cacheträff – loggas här (SPEC 7.2).

    En lyckad rad (status='ok') med samma cache_key fungerar också som svarscache (SPEC 2.4).
    """

    __tablename__ = "ai_run"
    project_id: Mapped[uuid.UUID | None] = _fk("project", nullable=True, ondelete="SET NULL")
    step: Mapped[str] = mapped_column(sa.String(20), index=True)  # uppgifts-id, t.ex. "T3"
    provider: Mapped[str] = mapped_column(sa.String(20))
    model: Mapped[str] = mapped_column(sa.String(100))  # begärd modell
    served_model: Mapped[str | None] = mapped_column(sa.String(100))  # modell som faktiskt svarade
    prompt_version: Mapped[str] = mapped_column(sa.String(20))
    input_hash: Mapped[str] = mapped_column(sa.String(64))
    cache_key: Mapped[str] = mapped_column(sa.String(64), index=True)
    attempt: Mapped[int] = mapped_column(sa.Integer, server_default="1")
    request_json: Mapped[dict[str, Any]]
    response_json: Mapped[dict[str, Any] | None]
    stop_reason: Mapped[str | None] = mapped_column(sa.String(40))
    tokens_in: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_out: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_cache_read: Mapped[int | None] = mapped_column(sa.Integer)
    tokens_cache_write: Mapped[int | None] = mapped_column(sa.Integer)
    cost_estimate: Mapped[Decimal | None] = mapped_column(sa.Numeric(12, 6))  # USD
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    status: Mapped[str] = mapped_column(
        enum_column(
            "ai_run_status",
            "ok",
            "cached",
            "invalid_output",
            "refused",
            "truncated",
            "api_error",
            "not_configured",
            "low_confidence",
        )
    )
    error: Mapped[str | None] = mapped_column(sa.Text)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
