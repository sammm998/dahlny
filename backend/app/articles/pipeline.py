"""TB-poster → matchning → Prixel-positioner (SPEC 6.3, 6.7)."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from app.ai.client import AIClient
from app.articles.match import ArticleSource, MatchInput, MatchResult, match_item
from app.export.prixel import ExportLine, ExportPosition, describe
from app.tb.extract import ItemDraft


def match_input(it: ItemDraft) -> MatchInput:
    key = f"{it.parent_designation} > {it.description}" if it.parent_designation else (it.designation or "")
    return MatchInput(
        key=key,
        designation=it.designation or it.parent_designation,
        description=it.description,
        manufacturer=it.manufacturer,
        model=it.model,
        article_no=it.article_no,
        rsk=it.rsk,
        dimension=it.dimension,
        requirements_text=it.requirements_text,
        refs=it.source_refs,
    )


def match_items(
    items: list[ItemDraft], source: ArticleSource, ai: AIClient | None, project_id: uuid.UUID | None = None
) -> list[MatchResult]:
    """Sakvaror (inte rör – de mängdas ur ritningen) matchas parallellt; ordningen följer posterna."""
    goods = [it for it in items if it.kind == "object"]
    workers = ai.config.defaults.max_concurrency if ai else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda it: match_item(match_input(it), source, ai, project_id), goods))


def positions(items: list[ItemDraft], results: list[MatchResult]) -> list[ExportPosition]:
    """En position per huvudpost med dess barnposter, i TB:ns ordning."""
    by_item = {id(it): r for it, r in zip([i for i in items if i.kind == "object"], results, strict=True)}
    out: list[ExportPosition] = []
    parents = [it for it in items if it.kind == "object" and it.parent_designation is None]
    for p in parents:
        lines = []
        for it in [p, *[c for c in items if c.parent_designation == p.designation]]:
            r = by_item.get(id(it))
            art = r.article if r else None
            lines.append(
                ExportLine(
                    article_no=art.dahl_art_no if art and r and r.outcome in ("stock", "virtual") else None,
                    name=art.name if art else it.description,
                    quantity=it.quantity,
                    unit=it.unit,
                    discount_group=art.discount_group if art else None,
                    supplier=art.supplier if art else it.manufacturer,
                    outcome=r.outcome if r else "request",
                    description=describe(it.dimension, it.requirements_text),
                )
            )
        out.append(ExportPosition(p.designation or p.description, lines))
    return out
