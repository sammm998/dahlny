"""Fas 2 till databasen: SpecItem (med barnposter), ProjectRule och Deviation."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.db.models import Deviation, ProjectRule, SpecItem
from app.rules.catalog import DeviationDraft
from app.tb.extract import ItemDraft, TBResult


def _spec(project_id: uuid.UUID, it: ItemDraft, parent_id: uuid.UUID | None) -> SpecItem:
    rng = (
        {"min": float(it.quantity_min), "max": float(it.quantity_max)}
        if it.quantity_min is not None and it.quantity_max is not None
        else None
    )
    refs = [dict(r, flags=it.flags, kind=it.kind, dimension=it.dimension) for r in it.source_refs]
    return SpecItem(
        id=uuid.uuid4(),
        project_id=project_id,
        ama_code=it.ama_code,
        ama_title=(it.ama_title or "")[:300] or None,
        designation=it.designation,
        description=it.description,
        manufacturer=it.manufacturer,
        model=it.model,
        article_no=it.article_no,
        rsk=it.rsk,
        quantity=it.quantity,
        unit=it.unit,
        quantity_mode=it.quantity_mode,
        quantity_range=rng,
        requirements_text=it.requirements_text,
        parent_item_id=parent_id,
        source_refs=refs,
    )


def save_deviations(session: Session, project_id: uuid.UUID, drafts: list[DeviationDraft]) -> list[Deviation]:
    rows = [
        Deviation(
            id=uuid.uuid4(),
            project_id=project_id,
            rule_id=d.rule_id,
            severity=d.effective_severity,
            message=d.message,
            refs=d.refs,
            question=d.question,
        )
        for d in drafts
    ]
    session.add_all(rows)
    return rows


def save_tb(session: Session, project_id: uuid.UUID, result: TBResult) -> list[SpecItem]:
    """Sparar poster, barnposter, generella krav och T4-avvikelserna. Returnerar huvudposterna."""
    out = []
    for it in result.items:
        parent = _spec(project_id, it, None)
        session.add(parent)
        session.flush()
        for ch in it.children:
            session.add(_spec(project_id, ch, parent.id))
        out.append(parent)
    for r in result.rules:
        session.add(
            ProjectRule(
                id=uuid.uuid4(),
                project_id=project_id,
                category=r.category[:50],
                text=r.text,
                applies_to_json={"applies_to": r.applies_to, "quote": r.quote},
                source_refs=r.source_refs,
            )
        )
    save_deviations(session, project_id, result.deviations)
    session.flush()
    return out
