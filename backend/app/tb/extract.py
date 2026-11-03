"""TB-extraktion (SPEC 6.2): layout → segment → T3 → validering → barnposter; T3G generella krav; T4
fullständighet.

Allt som modellen returnerar valideras mot källtexten (steg 5): RSK, art.nr, typ och citat måste finnas
ordagrant
efter att blanksteg tagits bort. Ett värde som inte finns avvisas (null) och posten flaggas – aldrig en tyst
gissning. Huvudpostens mängd tas deterministiskt ur MÄNGD-kolumnen; en barnposts antal måste stå i barnpostens
egen rad, annars ärver den huvudpostens antal (en "Härtill"-punkt utan antal levereras en gång per huvudpost).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.ai.client import AIClient, AIError
from app.ai.schemas.tb import T3GResponse, T3Response, T4Response, TBChild, TBItem
from app.ingest.pdf_typed import open_pdf
from app.rules.catalog import DeviationDraft
from app.tb.layout import TBLine, read_layout
from app.tb.quantity import parse_quantity
from app.tb.segment import Section, Segment, sections, segments

RSK_RE = re.compile(r"^\d{7}$")
CHILD_QTY_RE = re.compile(r"(\d+)\s*st\b", re.IGNORECASE)


def squash(text: str) -> str:
    """Jämförelseform: utan blanksteg och med enhetliga bindestreck, gemener."""
    return re.sub(r"\s+", "", text).replace("–", "-").replace("‐", "-").lower()


def found_in(value: str, source: str) -> bool:
    return bool(value.strip()) and squash(value) in squash(source)


@dataclass
class ItemDraft:
    designation: str | None
    parent_designation: str | None
    kind: str  # object | pipe
    ama_code: str | None
    ama_title: str | None
    description: str
    manufacturer: str | None
    model: str | None
    article_no: str | None
    rsk: str | None
    dimension: str | None
    quantity: Decimal | None
    quantity_min: Decimal | None
    quantity_max: Decimal | None
    unit: str | None
    quantity_mode: str
    requirements_text: str | None
    source_refs: list[dict[str, Any]]
    flags: list[str] = field(default_factory=list)
    children: list[ItemDraft] = field(default_factory=list)

    @property
    def key(self) -> tuple[str | None, str | None, str]:
        return (self.parent_designation, self.designation, self.description)


@dataclass
class RuleDraft:
    category: str
    text: str
    quote: str
    applies_to: list[str]
    source_refs: list[dict[str, Any]]


@dataclass
class TBResult:
    items: list[ItemDraft]
    rules: list[RuleDraft]
    deviations: list[DeviationDraft]
    segments: list[Segment]
    flags: list[str] = field(default_factory=list)

    def all_items(self) -> list[ItemDraft]:
        return [x for it in self.items for x in (it, *it.children)]


def _ref(seg_or_lines: Segment | list[TBLine], document: str, method: str, **extra: Any) -> dict[str, Any]:
    lines = seg_or_lines.lines if isinstance(seg_or_lines, Segment) else seg_or_lines
    first = lines[0]
    return {
        "document": document,
        "page": first.page,
        "bbox": list(first.bbox),
        "pages": sorted({ln.page for ln in lines}),
        "method": method,
        **extra,
    }


def _segment_block(seg: Segment) -> str:
    chain = " > ".join(f"{c} {t}".strip() for c, t in seg.section.chain)
    head = f'[SEGMENT {seg.sid} | beteckning {seg.designation} | mängd "{seg.quantity_text or ""}"]'
    return f"{head}\nRubrikkedja: {chain}\n{seg.text}"


def _checked(value: str | None, source: str, name: str, flags: list[str]) -> str | None:
    if value is None or not value.strip():
        return None
    if found_in(value, source):
        return value.strip()
    flags.append(f"rejected_{name}:{value}")
    return None


def _checked_rsk(value: str | None, source: str, flags: list[str]) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", value)
    if RSK_RE.match(digits) and re.search(rf"RSK\s*{digits[:3]}\s*{digits[3:]}", source.replace("\n", " ")):
        return digits
    if RSK_RE.match(digits) and digits in squash(source):
        return digits
    flags.append(f"rejected_rsk:{value}")
    return None


def _requirements(quotes: list[str], source: str, flags: list[str]) -> str | None:
    kept = [q.strip() for q in quotes if found_in(q, source)]
    dropped = len([q for q in quotes if q.strip()]) - len(kept)
    if dropped:
        flags.append(f"rejected_requirement_quotes:{dropped}")
    return "\n".join(kept) or None


def _child(c: TBChild, parent: ItemDraft, source: str, ref: dict[str, Any]) -> ItemDraft:
    flags: list[str] = []
    quote_ok = found_in(c.quote, source)
    if not quote_ok:
        flags.append("rejected_child_quote")
    qty: Decimal | None = parent.quantity if parent.quantity_mode == "fixed" else None
    if c.stated_quantity is not None:
        stated = [int(m) for m in CHILD_QTY_RE.findall(c.quote)] if quote_ok else []
        if c.stated_quantity in stated:
            qty = Decimal(c.stated_quantity)
        else:
            flags.append(f"rejected_child_quantity:{c.stated_quantity}")
    return ItemDraft(
        designation=None,
        parent_designation=parent.designation,
        kind="object",
        ama_code=parent.ama_code,
        ama_title=parent.ama_title,
        description=c.description.strip(),
        manufacturer=_checked(c.manufacturer, source, "manufacturer", flags),
        model=_checked(c.model, source, "model", flags),
        article_no=_checked(c.article_no, source, "article_no", flags),
        rsk=_checked_rsk(c.rsk, source, flags),
        dimension=None,
        quantity=qty,
        quantity_min=None,
        quantity_max=None,
        unit="st" if qty is not None else None,
        quantity_mode="fixed" if qty is not None else parent.quantity_mode,
        requirements_text=c.quote.strip() if quote_ok else None,
        source_refs=[{**ref, "quote": c.quote.strip() if quote_ok else None}],
        flags=flags,
    )


def _item(it: TBItem, seg: Segment, document: str, model: str) -> ItemDraft | None:
    source = seg.text
    flags: list[str] = []
    designation = it.designation.strip()
    if designation != seg.designation and not found_in(designation, source):
        return None  # en beteckning som inte står i segmentet är påhittad
    if it.kind == "pipe" or seg.kind == "pipe":
        pq = parse_quantity("Enl ritn")
        kind = "pipe"
    else:
        pq = seg.quantity
        kind = "object"
    if pq is None:
        flags.append("quantity_missing")
    ref = _ref(seg, document, f"tb_layout+T3:{model}", segment=seg.sid, quantity_text=seg.quantity_text)
    item = ItemDraft(
        designation=designation,
        parent_designation=None,
        kind=kind,
        ama_code=seg.section.code or None,
        ama_title=seg.section.title or None,
        description=it.description.strip(),
        manufacturer=_checked(it.manufacturer, source, "manufacturer", flags),
        model=_checked(it.model, source, "model", flags),
        article_no=_checked(it.article_no, source, "article_no", flags),
        rsk=_checked_rsk(it.rsk, source, flags),
        dimension=_checked(it.dimension, source, "dimension", flags),
        quantity=pq.quantity if pq else None,
        quantity_min=pq.minimum if pq else None,
        quantity_max=pq.maximum if pq else None,
        unit=pq.unit if pq else None,
        quantity_mode=pq.mode if pq else "fixed",
        requirements_text=_requirements(it.requirement_quotes, source, flags),
        source_refs=[ref],
        flags=flags,
    )
    item.children = [_child(c, item, source, ref) for c in it.children]
    return item


def _batches(segs: list[Segment]) -> list[list[Segment]]:
    by_section: dict[int, list[Segment]] = {}
    for s in segs:
        by_section.setdefault(id(s.section), []).append(s)
    return list(by_section.values())


def _section_intro(sec: Section, first: Segment) -> str:
    """Sektionens text före första segmentet (gemensamma krav för segmenten)."""
    start = next((i for i, ln in enumerate(sec.lines) if ln is first.lines[0]), 0)
    return "\n".join(ln.all_text for ln in sec.lines[:start])


def structure(
    segs: list[Segment],
    ai: AIClient,
    document: str,
    project_id: uuid.UUID | None,
    on_error: Callable[[str], None],
) -> list[ItemDraft]:
    """T3 per sektion (alla segment i sektionen i ett anrop). Ett misslyckat anrop flaggas, aldrig gissat."""
    model = ai.config.tasks["T3"].model

    def run(batch: list[Segment]) -> list[ItemDraft]:
        sec = batch[0].section
        text = "\n\n".join(
            [f"Sektion {sec.code} {sec.title}", _section_intro(sec, batch[0])]
            + [_segment_block(s) for s in batch]
        )
        try:
            resp = ai.structured("T3", text, T3Response, project_id=project_id)
        except AIError as exc:
            on_error(f"T3 {sec.code}: {exc}")
            return []
        by_id = {s.sid: s for s in batch}
        out: list[ItemDraft] = []
        for it in resp.items:
            seg = by_id.get(it.segment_id)
            if seg is None:
                continue
            item = _item(it, seg, document, model)
            if item is not None:
                out.append(item)
        return out

    with ThreadPoolExecutor(max_workers=ai.config.defaults.max_concurrency) as pool:
        results = list(pool.map(run, _batches(segs)))
    return merge_duplicates([x for r in results for x in r])


def merge_duplicates(items: list[ItemDraft]) -> list[ItemDraft]:
    """Samma beteckning i två sektioner (t.ex. VVB001 i PJE och som tillbehör i PSA.35) blir en post:
    den med mängd står, källorna läggs ihop."""
    out: dict[tuple[str | None, str], ItemDraft] = {}
    for it in items:
        key = (it.designation, it.kind) if it.kind == "object" else (it.designation, f"pipe:{it.ama_code}")
        prev = out.get(key)
        if prev is None:
            out[key] = it
            continue
        keep, other = (prev, it) if prev.quantity is not None or it.quantity is None else (it, prev)
        keep.source_refs += other.source_refs
        keep.children = keep.children or other.children
        out[key] = keep
    return list(out.values())


def general_rules(
    lines: list[TBLine],
    ai: AIClient,
    document: str,
    project_id: uuid.UUID | None,
    on_error: Callable[[str], None],
) -> list[RuleDraft]:
    text = "\n".join(f"[s{ln.page}] {ln.all_text}" for ln in lines)
    try:
        resp = ai.structured("T3G", text, T3GResponse, project_id=project_id)
    except AIError as exc:
        on_error(f"T3G: {exc}")
        return []
    model = ai.config.tasks["T3G"].model
    out = []
    whole = "\n".join(ln.all_text for ln in lines)
    for r in resp.rules:
        hit = next((ln for ln in lines if len(ln.all_text) > 10 and found_in(ln.all_text, r.quote)), None)
        if not found_in(r.quote, whole):
            on_error(f"T3G: citatet finns inte i TB: {r.quote[:60]}")
            continue
        refs = [_ref([hit], document, f"T3G:{model}", quote=r.quote)] if hit else []
        out.append(RuleDraft(r.category, r.text, r.quote, r.applies_to, refs))
    return out


def completeness(
    lines: list[TBLine],
    items: list[ItemDraft],
    ai: AIClient,
    document: str,
    project_id: uuid.UUID | None,
    on_error: Callable[[str], None],
) -> list[DeviationDraft]:
    """T4 (annan modell än T3): det som nämns men saknar post → TB_MENTIONED_NOT_ITEMIZED."""
    whole = "\n".join(ln.all_text for ln in lines)
    listing = "\n".join(
        f"- {it.designation or '(barnpost till ' + str(it.parent_designation) + ')'}: {it.description}"
        for it in items
    )
    text = f"# TB-text\n{whole}\n\n# Extraherade poster\n{listing}"
    try:
        resp = ai.structured("T4", text, T4Response, project_id=project_id)
    except AIError as exc:
        on_error(f"T4: {exc}")
        return []
    model = ai.config.tasks["T4"].model
    out = []
    for m in resp.missing:
        if not found_in(m.quote, whole):
            on_error(f"T4: citatet finns inte i TB: {m.quote[:60]}")
            continue
        hit = next((ln for ln in lines if found_in(ln.all_text, m.quote) and len(ln.all_text) > 10), None)
        refs = [_ref([hit], document, f"T4:{model}", quote=m.quote)] if hit else []
        out.append(
            DeviationDraft(
                "TB_MENTIONED_NOT_ITEMIZED",
                f'{m.name} nämns i TB men har ingen egen post: "{m.quote}"',
                refs,
                question=f"TB nämner {m.name} ({m.reason}) men det finns ingen post. Ska det ingå, och med "
                "vilken produkt och vilket antal?",
            )
        )
    return out


def extract_tb(
    pdf_bytes: bytes, document: str, ai: AIClient | None, project_id: uuid.UUID | None = None
) -> TBResult:
    """Hela fas 2 på en TB-PDF. Utan AI (`ai=None`) blir det bara segment – inga poster gissas."""
    with open_pdf(pdf_bytes) as doc:
        lines = read_layout(doc)
    segs = segments(sections(lines))
    flags: list[str] = []
    if ai is None:
        return TBResult([], [], [], segs, ["ai_disabled"])
    items = structure(segs, ai, document, project_id, flags.append)
    rules = general_rules(lines, ai, document, project_id, flags.append)
    deviations = completeness(
        lines, [x for it in items for x in (it, *it.children)], ai, document, project_id, flags.append
    )
    return TBResult(items, rules, deviations, segs, flags)
