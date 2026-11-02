"""ai_run.status: lägg till 'low_confidence' (konfidensstyrd eskalering, SPEC 7.1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02

Statusen är en VARCHAR med CHECK-villkor (native_enum=False). Autogenerate ser inte ändringar i CHECK-villkor,
så migreringen är handskriven.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_ai_run_ai_run_status"
OLD = ("ok", "cached", "invalid_output", "refused", "truncated", "api_error", "not_configured")
NEW = (*OLD, "low_confidence")


def _check(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "ai_run", type_="check")
    op.create_check_constraint("ai_run_status", "ai_run", _check(NEW))


def downgrade() -> None:
    op.execute("UPDATE ai_run SET status = 'ok' WHERE status = 'low_confidence'")
    op.drop_constraint(op.f(CONSTRAINT), "ai_run", type_="check")
    op.create_check_constraint("ai_run_status", "ai_run", _check(OLD))
