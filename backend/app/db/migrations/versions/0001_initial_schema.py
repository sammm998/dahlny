"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-02

Skapar extensions (PostGIS för geometri, pg_trgm för fuzzy artikelsök – SPEC 4) och alla tabeller i SPEC 5.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "article",
        sa.Column("dahl_art_no", sa.String(length=50), nullable=False),
        sa.Column("rsk", sa.String(length=20), nullable=True),
        sa.Column("supplier", sa.String(length=200), nullable=True),
        sa.Column("supplier_art_no", sa.String(length=100), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column(
            "stock_status",
            sa.Enum(
                "stock",
                "virtual",
                "order",
                name="stock_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("discount_group", sa.String(length=50), nullable=True),
        sa.Column("attributes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article")),
        sa.UniqueConstraint("dahl_art_no", name=op.f("uq_article_dahl_art_no")),
    )
    op.create_index(
        "ix_article_name_trgm",
        "article",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(op.f("ix_article_rsk"), "article", ["rsk"], unique=False)
    op.create_index(
        "ix_article_supplier_art_no_trgm",
        "article",
        ["supplier_art_no"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"supplier_art_no": "gin_trgm_ops"},
    )
    op.create_table(
        "project",
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("customer", sa.String(length=300), nullable=True),
        sa.Column("consultant", sa.String(length=300), nullable=True),
        sa.Column("project_no", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="new", nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
    )
    op.create_table(
        "style_profile",
        sa.Column("consultant", sa.String(length=300), nullable=False),
        sa.Column("label_regex_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("layer_map_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("line_width_map_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("legend_overrides_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("examples_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_style_profile")),
        sa.UniqueConstraint("consultant", "version", name="uq_style_profile_consultant_version"),
    )
    op.create_table(
        "ai_run",
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("step", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("served_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("stop_reason", sa.String(length=40), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("tokens_cache_read", sa.Integer(), nullable=True),
        sa.Column("tokens_cache_write", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "ok",
                "cached",
                "invalid_output",
                "refused",
                "truncated",
                "api_error",
                "not_configured",
                name="ai_run_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_ai_run_project_id_project"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_run")),
    )
    op.create_index(op.f("ix_ai_run_cache_key"), "ai_run", ["cache_key"], unique=False)
    op.create_index(op.f("ix_ai_run_project_id"), "ai_run", ["project_id"], unique=False)
    op.create_index(op.f("ix_ai_run_step"), "ai_run", ["step"], unique=False)
    op.create_table(
        "correction",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("entity", sa.String(length=60), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("field", sa.String(length=100), nullable=False),
        sa.Column("old", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("user", sa.String(length=200), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_correction_project_id_project"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correction")),
    )
    op.create_index(op.f("ix_correction_project_id"), "correction", ["project_id"], unique=False)
    op.create_table(
        "deviation",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("rule_id", sa.String(length=60), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "warning",
                "critical",
                name="severity",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "resolved",
                "ignored",
                name="deviation_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_deviation_project_id_project"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deviation")),
    )
    op.create_index(op.f("ix_deviation_project_id"), "deviation", ["project_id"], unique=False)
    op.create_index(op.f("ix_deviation_rule_id"), "deviation", ["rule_id"], unique=False)
    op.create_table(
        "document",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "tb",
                "drawing_list",
                "plan",
                "schematic",
                "section",
                "detail",
                "other",
                name="document_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "format",
            sa.Enum(
                "pdf_vector",
                "pdf_raster",
                "pdf_mixed",
                "image",
                "dwg",
                "dxf",
                "ifc",
                name="document_format",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("pages", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_document_project_id_project"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document")),
        sa.UniqueConstraint("project_id", "sha256", name="uq_document_project_sha256"),
    )
    op.create_index(op.f("ix_document_project_id"), "document", ["project_id"], unique=False)
    op.create_table(
        "pipe_run",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("system", sa.String(length=30), nullable=False),
        sa.Column("material", sa.String(length=30), nullable=True),
        sa.Column("dim", sa.String(length=30), nullable=True),
        sa.Column("length_m_horizontal", sa.Float(), server_default="0", nullable=False),
        sa.Column("length_m_vertical", sa.Float(), nullable=True),
        sa.Column("length_m_total", sa.Float(), nullable=True),
        sa.Column(
            "segment_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_pipe_run_project_id_project"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipe_run")),
    )
    op.create_index(op.f("ix_pipe_run_project_id"), "pipe_run", ["project_id"], unique=False)
    op.create_table(
        "project_rule",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("applies_to_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_project_rule_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_rule")),
    )
    op.create_index(op.f("ix_project_rule_project_id"), "project_rule", ["project_id"], unique=False)
    op.create_table(
        "spec_item",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("ama_code", sa.String(length=30), nullable=True),
        sa.Column("ama_title", sa.String(length=300), nullable=True),
        sa.Column("designation", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("manufacturer", sa.String(length=200), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("article_no", sa.String(length=100), nullable=True),
        sa.Column("rsk", sa.String(length=20), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column(
            "quantity_mode",
            sa.Enum(
                "fixed",
                "per_drawing",
                "range",
                "regulated",
                name="quantity_mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("quantity_range", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("requirements_text", sa.Text(), nullable=True),
        sa.Column("parent_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_item_id"],
            ["spec_item.id"],
            name=op.f("fk_spec_item_parent_item_id_spec_item"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_spec_item_project_id_project"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spec_item")),
    )
    op.create_index(op.f("ix_spec_item_designation"), "spec_item", ["designation"], unique=False)
    op.create_index(op.f("ix_spec_item_parent_item_id"), "spec_item", ["parent_item_id"], unique=False)
    op.create_index(op.f("ix_spec_item_project_id"), "spec_item", ["project_id"], unique=False)
    op.create_index(op.f("ix_spec_item_rsk"), "spec_item", ["rsk"], unique=False)
    op.create_table(
        "supplier_request",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("supplier", sa.String(length=200), nullable=False),
        sa.Column(
            "line_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "approved",
                "sent",
                "answered",
                name="supplier_request_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("reply_prices_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_supplier_request_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_request")),
    )
    op.create_index(op.f("ix_supplier_request_project_id"), "supplier_request", ["project_id"], unique=False)
    op.create_table(
        "page",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("width_pt", sa.Float(), nullable=False),
        sa.Column("height_pt", sa.Float(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "tb",
                "drawing_list",
                "plan",
                "schematic",
                "section",
                "detail",
                "other",
                "legend_only",
                name="page_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "format",
            sa.Enum(
                "pdf_vector",
                "pdf_raster",
                "pdf_mixed",
                "image",
                "dwg",
                "dxf",
                "ifc",
                name="page_format",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("title_block_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("drawing_no", sa.String(length=100), nullable=True),
        sa.Column("level_name", sa.String(length=200), nullable=True),
        sa.Column("scale_declared", sa.String(length=100), nullable=True),
        sa.Column("paper_size_declared", sa.String(length=20), nullable=True),
        sa.Column("scale_effective_m_per_pt", sa.Float(), nullable=True),
        sa.Column("scale_confidence", sa.Float(), nullable=True),
        sa.Column("scale_method", sa.String(length=50), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["document.id"], name=op.f("fk_page_document_id_document"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page")),
        sa.UniqueConstraint("document_id", "page_no", name="uq_page_document_page_no"),
    )
    op.create_index(op.f("ix_page_document_id"), "page", ["document_id"], unique=False)
    op.create_table(
        "quantity_line",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("spec_item_id", sa.UUID(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "tb",
                "drawing",
                "merged",
                name="quantity_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("designation", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "auto",
                "review",
                "approved",
                name="quantity_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="review",
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_quantity_line_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["spec_item_id"],
            ["spec_item.id"],
            name=op.f("fk_quantity_line_spec_item_id_spec_item"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quantity_line")),
    )
    op.create_index(op.f("ix_quantity_line_project_id"), "quantity_line", ["project_id"], unique=False)
    op.create_index(op.f("ix_quantity_line_spec_item_id"), "quantity_line", ["spec_item_id"], unique=False)
    op.create_table(
        "article_match",
        sa.Column("quantity_line_id", sa.UUID(), nullable=False),
        sa.Column("article_id", sa.UUID(), nullable=True),
        sa.Column(
            "method",
            sa.Enum(
                "rsk",
                "art_no",
                "fuzzy",
                "ai",
                name="match_method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "stock",
                "virtual",
                "request",
                "uncertain",
                name="match_outcome",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("approved_by", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["article.id"],
            name=op.f("fk_article_match_article_id_article"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["quantity_line_id"],
            ["quantity_line.id"],
            name=op.f("fk_article_match_quantity_line_id_quantity_line"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_match")),
    )
    op.create_index(op.f("ix_article_match_article_id"), "article_match", ["article_id"], unique=False)
    op.create_index(
        op.f("ix_article_match_quantity_line_id"), "article_match", ["quantity_line_id"], unique=False
    )
    op.create_geospatial_table(
        "label",
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column("raw_text", sa.String(length=300), nullable=False),
        sa.Column(
            "bbox",
            Geometry(
                geometry_type="POLYGON",
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("rotation", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "read_method",
            sa.Enum(
                "text_layer",
                "vision",
                "ocr",
                name="read_method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("read_confidence", sa.Float(), nullable=False),
        sa.Column("parsed_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "parse_status",
            sa.Enum(
                "ok",
                "unknown_token",
                "failed",
                name="parse_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_id"], ["page.id"], name=op.f("fk_label_page_id_page"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_label")),
    )
    op.create_geospatial_index(
        "idx_label_bbox", "label", ["bbox"], unique=False, postgresql_using="gist", postgresql_ops={}
    )
    op.create_index(op.f("ix_label_page_id"), "label", ["page_id"], unique=False)
    op.create_table(
        "legend",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("page_id", sa.UUID(), nullable=True),
        sa.Column(
            "materials_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "systems_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "notes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_id"], ["page.id"], name=op.f("fk_legend_page_id_page"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_legend_project_id_project"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legend")),
    )
    op.create_index(op.f("ix_legend_page_id"), "legend", ["page_id"], unique=False)
    op.create_index(op.f("ix_legend_project_id"), "legend", ["project_id"], unique=False)
    op.create_geospatial_table(
        "symbol",
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("tag", sa.String(length=100), nullable=True),
        sa.Column(
            "bbox",
            Geometry(
                geometry_type="POLYGON",
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("read_method", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("linked_spec_item_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["linked_spec_item_id"],
            ["spec_item.id"],
            name=op.f("fk_symbol_linked_spec_item_id_spec_item"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["page.id"], name=op.f("fk_symbol_page_id_page"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_symbol")),
    )
    op.create_geospatial_index(
        "idx_symbol_bbox", "symbol", ["bbox"], unique=False, postgresql_using="gist", postgresql_ops={}
    )
    op.create_index(op.f("ix_symbol_linked_spec_item_id"), "symbol", ["linked_spec_item_id"], unique=False)
    op.create_index(op.f("ix_symbol_page_id"), "symbol", ["page_id"], unique=False)
    op.create_geospatial_table(
        "pipe_segment",
        sa.Column("page_id", sa.UUID(), nullable=False),
        sa.Column(
            "geom",
            Geometry(
                geometry_type="LINESTRING",
                dimension=2,
                spatial_index=False,
                from_text="ST_GeomFromEWKT",
                name="geometry",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column("length_pt", sa.Float(), nullable=False),
        sa.Column("length_m", sa.Float(), nullable=True),
        sa.Column("stroke_width", sa.Float(), nullable=True),
        sa.Column("dash_pattern", sa.String(length=100), nullable=True),
        sa.Column("color", sa.String(length=30), nullable=True),
        sa.Column("layer", sa.String(length=200), nullable=True),
        sa.Column("assigned_label_id", sa.UUID(), nullable=True),
        sa.Column("system", sa.String(length=30), nullable=True),
        sa.Column("material", sa.String(length=30), nullable=True),
        sa.Column("dim", sa.String(length=30), nullable=True),
        sa.Column("assign_method", sa.String(length=30), nullable=True),
        sa.Column("assign_confidence", sa.Float(), nullable=True),
        sa.Column("is_vertical_symbol", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("z_from_m", sa.Float(), nullable=True),
        sa.Column("z_to_m", sa.Float(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_label_id"],
            ["label.id"],
            name=op.f("fk_pipe_segment_assigned_label_id_label"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["page.id"], name=op.f("fk_pipe_segment_page_id_page"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipe_segment")),
    )
    op.create_geospatial_index(
        "idx_pipe_segment_geom",
        "pipe_segment",
        ["geom"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(
        op.f("ix_pipe_segment_assigned_label_id"), "pipe_segment", ["assigned_label_id"], unique=False
    )
    op.create_index(op.f("ix_pipe_segment_page_id"), "pipe_segment", ["page_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pipe_segment_page_id"), table_name="pipe_segment")
    op.drop_index(op.f("ix_pipe_segment_assigned_label_id"), table_name="pipe_segment")
    op.drop_geospatial_index(
        "idx_pipe_segment_geom", table_name="pipe_segment", postgresql_using="gist", column_name="geom"
    )
    op.drop_geospatial_table("pipe_segment")
    op.drop_index(op.f("ix_symbol_page_id"), table_name="symbol")
    op.drop_index(op.f("ix_symbol_linked_spec_item_id"), table_name="symbol")
    op.drop_geospatial_index(
        "idx_symbol_bbox", table_name="symbol", postgresql_using="gist", column_name="bbox"
    )
    op.drop_geospatial_table("symbol")
    op.drop_index(op.f("ix_legend_project_id"), table_name="legend")
    op.drop_index(op.f("ix_legend_page_id"), table_name="legend")
    op.drop_table("legend")
    op.drop_index(op.f("ix_label_page_id"), table_name="label")
    op.drop_geospatial_index(
        "idx_label_bbox", table_name="label", postgresql_using="gist", column_name="bbox"
    )
    op.drop_geospatial_table("label")
    op.drop_index(op.f("ix_article_match_quantity_line_id"), table_name="article_match")
    op.drop_index(op.f("ix_article_match_article_id"), table_name="article_match")
    op.drop_table("article_match")
    op.drop_index(op.f("ix_quantity_line_spec_item_id"), table_name="quantity_line")
    op.drop_index(op.f("ix_quantity_line_project_id"), table_name="quantity_line")
    op.drop_table("quantity_line")
    op.drop_index(op.f("ix_page_document_id"), table_name="page")
    op.drop_table("page")
    op.drop_index(op.f("ix_supplier_request_project_id"), table_name="supplier_request")
    op.drop_table("supplier_request")
    op.drop_index(op.f("ix_spec_item_rsk"), table_name="spec_item")
    op.drop_index(op.f("ix_spec_item_project_id"), table_name="spec_item")
    op.drop_index(op.f("ix_spec_item_parent_item_id"), table_name="spec_item")
    op.drop_index(op.f("ix_spec_item_designation"), table_name="spec_item")
    op.drop_table("spec_item")
    op.drop_index(op.f("ix_project_rule_project_id"), table_name="project_rule")
    op.drop_table("project_rule")
    op.drop_index(op.f("ix_pipe_run_project_id"), table_name="pipe_run")
    op.drop_table("pipe_run")
    op.drop_index(op.f("ix_document_project_id"), table_name="document")
    op.drop_table("document")
    op.drop_index(op.f("ix_deviation_rule_id"), table_name="deviation")
    op.drop_index(op.f("ix_deviation_project_id"), table_name="deviation")
    op.drop_table("deviation")
    op.drop_index(op.f("ix_correction_project_id"), table_name="correction")
    op.drop_table("correction")
    op.drop_index(op.f("ix_ai_run_step"), table_name="ai_run")
    op.drop_index(op.f("ix_ai_run_project_id"), table_name="ai_run")
    op.drop_index(op.f("ix_ai_run_cache_key"), table_name="ai_run")
    op.drop_table("ai_run")
    op.drop_table("style_profile")
    op.drop_table("project")
    op.drop_index(
        "ix_article_supplier_art_no_trgm",
        table_name="article",
        postgresql_using="gin",
        postgresql_ops={"supplier_art_no": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_article_rsk"), table_name="article")
    op.drop_index(
        "ix_article_name_trgm",
        table_name="article",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_table("article")
