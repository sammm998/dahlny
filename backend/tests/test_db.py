from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from geoalchemy2 import alembic_helpers
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Article, Document, Label, Page, PipeSegment, Project


def test_extensions_installed(db_engine: Engine) -> None:
    with db_engine.connect() as conn:
        exts = set(conn.scalars(text("SELECT extname FROM pg_extension")).all())
    assert {"postgis", "pg_trgm"} <= exts


def test_migrations_match_models(db_engine: Engine) -> None:
    with db_engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={"include_object": alembic_helpers.include_object, "compare_type": True},
        )
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], f"Modeller och migreringar skiljer sig – skapa en ny migrering: {diff}"


def test_geometry_roundtrip_and_length(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        project = Project(name="Testprojekt")
        s.add(project)
        s.flush()
        doc = Document(
            project_id=project.id, filename="plan.pdf", format="pdf_vector", sha256="a" * 64, pages=1
        )
        s.add(doc)
        s.flush()
        page = Page(document_id=doc.id, page_no=1, width_pt=595.0, height_pt=842.0, kind="plan")
        s.add(page)
        s.flush()
        label = Label(
            page_id=page.id,
            raw_text="KV01-K1-15-W40",
            bbox="POLYGON((10 10, 60 10, 60 20, 10 20, 10 10))",
            read_method="vision",
            read_confidence=0.97,
            parse_status="unknown_token",
        )
        seg = PipeSegment(page_id=page.id, geom="LINESTRING(0 100, 30 140)", length_pt=50.0)
        s.add_all([label, seg])
        s.commit()
        length = s.scalar(select(func.ST_Length(PipeSegment.geom)))
        assert length == 50.0
        near = s.scalar(
            select(func.ST_Distance(Label.bbox, PipeSegment.geom))
            .select_from(Label)
            .join(PipeSegment, Label.page_id == PipeSegment.page_id)
        )
        assert near is not None and near > 0


def test_trigram_similarity_on_articles(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        s.add_all(
            [
                Article(
                    dahl_art_no="142B1106",
                    name="Golvbrunn FURO 142",
                    stock_status="order",
                    supplier="Furhoffs",
                ),
                Article(dahl_art_no="1", name="Tvättställ IFÖ Cera", stock_status="stock"),
            ]
        )
        s.commit()
        best = s.scalars(
            select(Article.dahl_art_no)
            .order_by(func.similarity(Article.name, "golvbrunn furo").desc())
            .limit(1)
        ).first()
    assert best == "142B1106"


def test_enum_check_constraint_rejects_unknown_value(session_factory: sessionmaker[Session]) -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError, StatementError

    with session_factory() as s:
        project = Project(name="X")
        s.add(project)
        s.flush()
        s.add(Document(project_id=project.id, filename="x", format="docx", sha256="b" * 64))
        with pytest.raises((IntegrityError, StatementError)):
            s.flush()
