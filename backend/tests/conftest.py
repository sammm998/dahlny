"""Gemensamma fixturer.

Databastester körs mot en riktig PostgreSQL 16 + PostGIS + pg_trgm (SPEC 4) på TEST_DATABASE_URL.
Schemat byggs om från Alembic-migreringarna en gång per testkörning, så migreringarna testas alltid.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_TEST_DB = "postgresql+psycopg://vskalkyl:vskalkyl@localhost:5432/vskalkyl_test"


def test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)


def run_alembic(url: str, action: str, target: str) -> None:
    """Kör Alembic programmatiskt; env.py läser `-x url=...`, som här sätts via cmd_opts."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "app" / "db" / "migrations"))
    cfg.cmd_opts = argparse.Namespace(x=[f"url={url}"])
    getattr(command, action)(cfg, target)


def reset_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = test_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        pytest.exit(
            f"Testdatabasen nås inte på {url}. Starta den med `make db-up` (Docker) eller sätt "
            f"TEST_DATABASE_URL. Fel: {exc.orig}",
            returncode=2,
        )
    reset_schema(engine)
    run_alembic(url, "upgrade", "head")
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(db_engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(bind=db_engine, expire_on_commit=False)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with db_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
