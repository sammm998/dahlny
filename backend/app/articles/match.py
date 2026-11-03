"""Artikelmatchning (SPEC 6.3): RSK → leverantörens art.nr → trigram (pg_trgm) → AI-rerank (T6) → utfall.

Kedjan stannar vid första säkra träffen. T6 får bara välja bland kandidaterna; ett val utanför listan avvisas.
Utfall: `stock`/`virtual` vid score ≥ stock_min_score och lagerstatus lager/virtuellt; `request` när ingen
kandidat
når request_below_score eller artikeln är beställningsvara; annars `uncertain` (granskas). Kräver TB tillbehör
som
artikeln inte bekräftar blir raden `request` och en ACCESSORY_NOT_CONFIRMED-avvikelse (SPEC 6.3 steg 6).
Trösklar och tillbehörsord: `config/articles.yaml`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai.client import AIClient, AIError
from app.articles.register import ArticleRow
from app.config.settings import load_articles_config
from app.db.models import Article
from app.rules.engine import AccessoryCheck


@dataclass
class MatchInput:
    key: str  # t.ex. beteckning eller "TS101 > Silventil"
    designation: str | None
    description: str
    manufacturer: str | None = None
    model: str | None = None
    article_no: str | None = None
    rsk: str | None = None
    dimension: str | None = None
    requirements_text: str | None = None
    refs: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Candidate:
    article: ArticleRow
    similarity: float


@dataclass
class MatchResult:
    input: MatchInput
    article: ArticleRow | None
    method: str  # rsk | art_no | fuzzy | ai | none
    score: float
    outcome: str  # stock | virtual | request | uncertain
    reason: str
    candidates: list[Candidate] = field(default_factory=list)
    accessory: AccessoryCheck | None = None


class ArticleSource(Protocol):
    def by_rsk(self, rsk: str) -> list[ArticleRow]: ...
    def by_art_no(self, normalized: str) -> list[ArticleRow]: ...
    def fuzzy(self, query: str, limit: int) -> list[Candidate]: ...


def normalize_art_no(value: str | None) -> str:
    return re.sub(r"[\s\-./]", "", value or "").upper()


def _trigrams(s: str) -> set[str]:
    """Samma trigram som pg_trgm: gemener, ord med två blanksteg före och ett efter."""
    out: set[str] = set()
    for w in re.findall(r"[a-zåäö0-9]+", s.lower()):
        p = f"  {w} "
        out |= {p[i : i + 3] for i in range(len(p) - 2)}
    return out


def similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


def _text_of(a: ArticleRow) -> str:
    return " ".join(p for p in (a.supplier, a.name, a.supplier_art_no) if p)


class MemoryArticleSource:
    """Register i minnet (t.ex. en importerad fil) – för utvärdering och demo utan att röra databasens
    register."""

    def __init__(self, rows: list[ArticleRow]) -> None:
        self.rows = rows

    def by_rsk(self, rsk: str) -> list[ArticleRow]:
        return [r for r in self.rows if r.rsk == rsk]

    def by_art_no(self, normalized: str) -> list[ArticleRow]:
        return [r for r in self.rows if normalized and normalize_art_no(r.supplier_art_no) == normalized]

    def fuzzy(self, query: str, limit: int) -> list[Candidate]:
        scored = [Candidate(r, similarity(query, _text_of(r))) for r in self.rows]
        return sorted(scored, key=lambda c: (-c.similarity, c.article.dahl_art_no))[:limit]


def _row(a: Article) -> ArticleRow:
    attrs = dict(a.attributes_json or {})
    acc = attrs.pop("accessories", [])
    return ArticleRow(
        a.dahl_art_no,
        a.name,
        a.stock_status,
        a.rsk,
        a.supplier,
        a.supplier_art_no,
        a.unit,
        a.discount_group,
        list(acc) if isinstance(acc, list) else [],
        attrs,
    )


class DbArticleSource:
    """Registret i databasen; fuzzy-steget med pg_trgm (`similarity`) på leverantör + benämning + art.nr."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def by_rsk(self, rsk: str) -> list[ArticleRow]:
        return [_row(a) for a in self.session.scalars(select(Article).where(Article.rsk == rsk))]

    def by_art_no(self, normalized: str) -> list[ArticleRow]:
        q = select(Article).where(
            text("upper(regexp_replace(coalesce(supplier_art_no, ''), '[\\s\\-./]', '', 'g')) = :n")
        )
        return [_row(a) for a in self.session.scalars(q, {"n": normalized})]

    def fuzzy(self, query: str, limit: int) -> list[Candidate]:
        sql = text(
            "SELECT id, similarity(coalesce(supplier,'') || ' ' || name || ' ' || "
            "coalesce(supplier_art_no,''), :q)"
            " AS s FROM article ORDER BY s DESC, dahl_art_no LIMIT :n"
        )
        hits = self.session.execute(sql, {"q": query, "n": limit}).all()
        arts = {
            a.id: a for a in self.session.scalars(select(Article).where(Article.id.in_([h[0] for h in hits])))
        }
        return [Candidate(_row(arts[h[0]]), float(h[1])) for h in hits]


class RerankChoice(BaseModel):
    candidate: int | None = Field(description="Index i kandidatlistan, eller null om ingen passar")
    score: float = Field(ge=0, le=1, description="Hur säkert valet är, 0–1")
    reason: str = Field(description="Kort motivering på svenska: vad som stämmer och vad som skiljer")


def required_accessories(item: MatchInput) -> list[str]:
    """Tillbehör som TB säger att produkten levereras med ("Levereras med rutgaller M125", "försedd med
    skyddslock"). Ett tillbehör som bara nämns – t.ex. som en egen Härtill-post – krävs inte av artikeln."""
    cfg = load_articles_config()
    sentences = re.split(r"(?<=[.!?])\s+|\n", f"{item.description}. {item.requirements_text or ''}".lower())
    delivered = [s for s in sentences if any(c in s for c in cfg.accessory_context)]
    return [name for name, words in cfg.accessories.items() if any(w in s for s in delivered for w in words)]


def confirmed(article: ArticleRow, accessory: str) -> bool:
    words = load_articles_config().accessories[accessory]
    have = " ".join([article.name, *article.accessories]).lower()
    return any(w in have for w in words)


def _outcome(article: ArticleRow | None, score: float) -> str:
    cfg = load_articles_config().match
    if article is None or score < cfg.request_below_score or article.stock_status == "order":
        return "request"
    if score >= cfg.stock_min_score:
        return article.stock_status  # stock | virtual
    return "uncertain"


def _query(item: MatchInput) -> str:
    return " ".join(
        p for p in (item.manufacturer, item.model, item.dimension, item.article_no, item.description) if p
    )


def _rerank(
    item: MatchInput, cands: list[Candidate], ai: AIClient, project_id: uuid.UUID | None
) -> RerankChoice:
    listing = "\n".join(
        f"[{i}] {c.article.supplier or ''} | {c.article.name} | "
        f"lev.art.nr {c.article.supplier_art_no or '–'} | "
        f"RSK {c.article.rsk or '–'} | tillbehör: {', '.join(c.article.accessories) or '–'}"
        for i, c in enumerate(cands)
    )
    prompt = (
        f"# Post ur TB\nBeteckning: {item.designation or '–'}\nProdukt: {item.description}\n"
        f"Fabrikat: {item.manufacturer or '–'}\nTyp: {item.model or '–'}\nArt.nr: {item.article_no or '–'}\n"
        f"Dimension: {item.dimension or '–'}\nKrav: {item.requirements_text or '–'}\n\n"
        f"# Kandidater\n{listing}"
    )
    return ai.structured("T6", prompt, RerankChoice, project_id=project_id)


def match_item(
    item: MatchInput, source: ArticleSource, ai: AIClient | None = None, project_id: uuid.UUID | None = None
) -> MatchResult:
    cfg = load_articles_config().match
    article: ArticleRow | None = None
    method, score, reason, cands = "none", 0.0, "", []
    if item.rsk:
        hits = source.by_rsk(item.rsk)
        if len(hits) == 1:
            article, method, score, reason = hits[0], "rsk", cfg.rsk_score, f"RSK {item.rsk} exakt"
    if article is None and item.article_no:
        norm = normalize_art_no(item.article_no)
        hits = source.by_art_no(norm)
        if item.manufacturer:
            m = item.manufacturer.lower()
            hits = [h for h in hits if not h.supplier or h.supplier.lower() in m or m in h.supplier.lower()]
        if len(hits) == 1:
            article, method, score = hits[0], "art_no", cfg.art_no_score
            reason = f"leverantörens art.nr {item.article_no} exakt, fabrikat stämmer"
    if article is None:
        cands = [
            c
            for c in source.fuzzy(_query(item), cfg.fuzzy_candidates)
            if c.similarity >= cfg.fuzzy_min_similarity
        ]
        if cands and ai is not None:
            try:
                choice = _rerank(item, cands, ai, project_id)
                if choice.candidate is not None and 0 <= choice.candidate < len(cands):
                    article, method, score, reason = (
                        cands[choice.candidate].article,
                        "ai",
                        choice.score,
                        choice.reason,
                    )
                else:
                    reason = f"T6: ingen kandidat passar – {choice.reason}"
            except AIError as exc:
                reason = f"T6 misslyckades ({type(exc).__name__}) – granskas"
                if cands:
                    article, method, score = cands[0].article, "fuzzy", min(cands[0].similarity, 0.59)
        elif cands:
            article, method, score = cands[0].article, "fuzzy", cands[0].similarity
            reason = "närmaste trigramträff utan AI-rerank – granskas"
        else:
            reason = "ingen kandidat i registret"
    outcome = _outcome(article, score)
    acc = None
    if article is not None:
        missing = [a for a in required_accessories(item) if not confirmed(article, a)]
        if missing:
            acc = AccessoryCheck(item.key, article.dahl_art_no, missing, item.refs)
            outcome = "request"
    return MatchResult(item, article, method, score, outcome, reason, cands, acc)
