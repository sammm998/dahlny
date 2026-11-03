"""Avstämnings- och avvikelsemotorn (SPEC 6.5).

Varje regel är en funktion registrerad med `@rule(id)`; graden står i `catalog.SEVERITY`. En regel får en
`RuleContext` (det som är känt om projektet: TB-poster och -text, fas 1:s korskontroller, ritningsmängder,
matchningar)
och returnerar avvikelser med källhänvisningar och en föreslagen fråga. En regel som saknar sitt underlag
(t.ex.
ritningsregler utan ritningsmängd) returnerar ingenting – den gissar inte. Ordlistor och mönster:
`config/rules.yaml`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import load_label_grammar, load_rules_config
from app.drawings.checks import Finding
from app.drawings.source import DrawingTakeoff
from app.rules.catalog import SEVERITY, DeviationDraft
from app.tb.dimensions import find_dimensions
from app.tb.extract import ItemDraft, TBResult, squash
from app.tb.layout import TBLine

RuleFn = Callable[["RuleContext"], list[DeviationDraft]]
SEVERITY_LEVELS = ("info", "warning", "critical")


@dataclass(frozen=True)
class Rule:
    id: str
    fn: RuleFn
    description: str

    @property
    def severity(self) -> str:
        return SEVERITY[self.id]


RULES: dict[str, Rule] = {}


def rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    if rule_id not in SEVERITY:
        raise KeyError(f"Okänd regel {rule_id} – lägg till den i app/rules/catalog.py")

    def register(fn: RuleFn) -> RuleFn:
        RULES[rule_id] = Rule(rule_id, fn, (fn.__doc__ or "").strip().split("\n")[0])
        return fn

    return register


@dataclass
class AccessoryCheck:
    """En matchad artikel och de tillbehör TB kräver som artikeln inte bekräftar (fas 4)."""

    designation: str
    article: str
    missing: list[str]
    refs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RuleContext:
    tb: TBResult | None = None
    document: str = "TB"
    phase1: list[DeviationDraft] = field(default_factory=list)
    takeoff: DrawingTakeoff | None = None
    drawing_findings: list[Finding] = field(default_factory=list)
    drawing_tags: dict[str, int] = field(default_factory=dict)  # objektbeteckning → antal på planerna
    drawing_pipe_labels: list[str] = field(default_factory=list)  # rörbeteckningar lästa på planerna
    quantity_flags: list[tuple[str, str]] = field(default_factory=list)  # (mängdrad, flagga)
    accessories: list[AccessoryCheck] = field(default_factory=list)

    @property
    def items(self) -> list[ItemDraft]:
        return self.tb.all_items() if self.tb else []


def run_rules(ctx: RuleContext, only: Iterable[str] | None = None) -> list[DeviationDraft]:
    wanted = set(only) if only else set(RULES)
    out: list[DeviationDraft] = []
    for rid in sorted(wanted):
        out += RULES[rid].fn(ctx)
    return out


# --------------------------------------------------------------------------- textverktyg


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ0-9])")


@dataclass
class Sentence:
    text: str
    line: TBLine
    segment: str | None  # beteckningen om meningen står i ett segment


def sentences(tb: TBResult) -> list[Sentence]:
    """TB:ns text mening för mening, med raden där meningen börjar och segmentets beteckning."""
    seg_of: dict[int, str] = {}
    for s in tb.segments:
        for ln in s.lines:
            seg_of[id(ln)] = s.designation
    out: list[Sentence] = []
    buf: list[TBLine] = []

    def flush() -> None:
        if not buf:
            return
        starts: list[int] = []  # var i den hopfogade texten varje rad börjar
        pos = 0
        for ln in buf:
            starts.append(pos)
            pos += len(ln.text) + 1
        text = " ".join(ln.text for ln in buf)
        cursor = 0
        for part in SENTENCE_END.split(text):
            part = part.strip()
            if not part:
                continue
            at = text.find(part, cursor)
            cursor = at + len(part) if at >= 0 else cursor
            idx = max(i for i, st in enumerate(starts) if st <= max(at, 0))
            start = buf[idx]
            out.append(Sentence(part, start, seg_of.get(id(start))))
        buf.clear()

    for ln in tb.lines:
        if ln.kod.strip() or not ln.text.strip():
            flush()
        if ln.text.strip():
            buf.append(ln)
    flush()
    return out


def _ref(ctx: RuleContext, line: TBLine, **extra: Any) -> dict[str, Any]:
    return {"document": ctx.document, "page": line.page, "bbox": list(line.bbox), "method": "rule", **extra}


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


# --------------------------------------------------------------------------- TB-regler


@rule("TB_MENTIONED_NOT_ITEMIZED")
def tb_mentioned_not_itemized(ctx: RuleContext) -> list[DeviationDraft]:
    """Objekt/produkt som nämns i TB men saknar post (T4:s andra läsning, citat validerat)."""
    return [d for d in (ctx.tb.deviations if ctx.tb else []) if d.rule_id == "TB_MENTIONED_NOT_ITEMIZED"]


@rule("CONFLICTING_REQUIREMENTS")
def conflicting_requirements(ctx: RuleContext) -> list[DeviationDraft]:
    """Två krav på samma sak som utesluter varandra (T3, båda citaten validerade)."""
    return [d for d in (ctx.tb.deviations if ctx.tb else []) if d.rule_id == "CONFLICTING_REQUIREMENTS"]


@rule("TB_SELF_CONTRADICTION")
def tb_self_contradiction(ctx: RuleContext) -> list[DeviationDraft]:
    """Samma post har olika mått efter samma specifikationsord, eller två specifikationsord utan värde."""
    if ctx.tb is None:
        return []
    cfg = load_rules_config()
    labels = "|".join(re.escape(w) for w in cfg.spec_labels)
    label_re = re.compile(rf"\b({labels})\b", re.IGNORECASE)
    empty_re = re.compile(rf"\b({labels})\b\s+({labels})\b(?!\s*[:\d])", re.IGNORECASE)
    out: list[DeviationDraft] = []
    for seg in ctx.tb.segments:
        text = seg.text
        by_label: dict[str, list[tuple[str, tuple[Any, ...]]]] = defaultdict(list)
        for dim in find_dimensions(text):
            if len(dim.values_mm) < 3:
                continue
            before = text[max(0, dim.start - cfg.spec_label_reach_chars) : dim.start]
            m = list(label_re.finditer(before))
            if m:
                by_label[m[-1].group(1).lower()].append((dim.raw, dim.values_mm))
        for label, dims in by_label.items():
            distinct = {v for _, v in dims}
            if len(distinct) > 1:
                raws = " / ".join(dict.fromkeys(r for r, _ in dims))
                out.append(
                    DeviationDraft(
                        "TB_SELF_CONTRADICTION",
                        f"{seg.designation}: {label} anges olika i samma post ({raws}).",
                        [_ref(ctx, seg.lines[0], segment=seg.sid)],
                        question=f"TB anger {label} för {seg.designation} som {raws}. Vilket mått gäller?",
                    )
                )
        for ln in seg.lines:
            e = empty_re.search(ln.text)
            if e and e.group(1).lower() != e.group(2).lower():
                out.append(
                    DeviationDraft(
                        "TB_SELF_CONTRADICTION",
                        f'{seg.designation}: ofullständig mening "{e.group(0)} …" – '
                        f"värdet för {e.group(1)} saknas.",
                        [_ref(ctx, ln, segment=seg.sid)],
                        question=f'I posten {seg.designation} står "{e.group(0)}" utan värde. Vad ska stå?',
                        severity="info",
                    )
                )
    return out


def _phrase_hits(ctx: RuleContext, patterns: list[re.Pattern[str]]) -> dict[str, list[Sentence]]:
    hits: dict[str, list[Sentence]] = defaultdict(list)
    for s in sentences(ctx.tb) if ctx.tb else []:
        if any(p.search(s.text) for p in patterns):
            hits[squash(s.text)].append(s)
    return hits


@rule("OPTION_REQUIRED")
def option_required(ctx: RuleContext) -> list[DeviationDraft]:
    """TB säger att något ska ingå i anbudet men utreds senare. Samma mening i flera poster blir en
    avvikelse."""
    out = []
    for group in _phrase_hits(ctx, _compile(load_rules_config().option_phrases)).values():
        where = sorted({s.segment for s in group if s.segment})
        subject = "/".join(where) or "TB"
        out.append(
            DeviationDraft(
                "OPTION_REQUIRED",
                f'{subject}: "{group[0].text}" – prissätt som option.',
                [_ref(ctx, s.line, segment=s.segment) for s in group],
                question=f'"{group[0].text}" ({subject}): vilken omfattning ska optionen prissättas med?',
            )
        )
    return out


@rule("DECIDE_WITH_CLIENT")
def decide_with_client(ctx: RuleContext) -> list[DeviationDraft]:
    """Ett produktval som enligt TB görs i samråd med beställaren eller kommunen."""
    cfg = load_rules_config()
    phrases = _compile(cfg.decide_phrases)
    words = re.compile(r"\b(" + "|".join(map(re.escape, cfg.decide_selection_words)) + r")\b", re.IGNORECASE)
    out = []
    for group in _phrase_hits(ctx, phrases).values():
        s = group[0]
        hit = next((p.search(s.text) for p in phrases if p.search(s.text)), None)
        if hit is None or not words.search(s.text[: hit.start()]):
            continue  # samråd om utförande, inte ett produktval
        out.append(
            DeviationDraft(
                "DECIDE_WITH_CLIENT",
                f'{s.segment or "TB"}: "{s.text}"',
                [_ref(ctx, x.line, segment=x.segment) for x in group],
                question=f'TB: "{s.text}" Vilket val gäller för anbudet?',
            )
        )
    return out


@rule("UNDEFINED_VALUE")
def undefined_value(ctx: RuleContext) -> list[DeviationDraft]:
    """Platshållare i stället för värden ("DN XX") och mängder som intervall ("1-2 st")."""
    if ctx.tb is None:
        return []
    pats = _compile(load_rules_config().placeholder_patterns)
    out = []
    for seg in ctx.tb.segments:
        found = [m.group(0) for p in pats for ln in seg.lines for m in p.finditer(ln.all_text)]
        if seg.quantity and seg.quantity.mode == "range":
            found.append(seg.quantity.text)
        if found:
            vals = ", ".join(dict.fromkeys(found))
            out.append(
                DeviationDraft(
                    "UNDEFINED_VALUE",
                    f"{seg.designation}: odefinierade värden ({vals}).",
                    [_ref(ctx, seg.lines[0], segment=seg.sid)],
                    question=f"{seg.designation} anger {vals}. Vilka värden ska anbudet räknas på?",
                )
            )
    return out


# --------------------------------------------------------------------------- fas 1 och ritning


@rule("TITLEBLOCK_MISMATCH")
def titleblock_mismatch(ctx: RuleContext) -> list[DeviationDraft]:
    """Uppdragsnummer, datum eller skala skiljer mellan TB, förteckning och titelblock (fas 1)."""
    return [d for d in ctx.phase1 if d.rule_id == "TITLEBLOCK_MISMATCH"]


@rule("DRAWING_LIST_MISMATCH")
def drawing_list_mismatch(ctx: RuleContext) -> list[DeviationDraft]:
    """Ritning i förteckningen saknas eller finns utöver (fas 1)."""
    return [d for d in ctx.phase1 if d.rule_id == "DRAWING_LIST_MISMATCH"]


def _from_findings(ctx: RuleContext, rule_id: str) -> list[DeviationDraft]:
    return [
        DeviationDraft(
            f.rule_id,
            f.message,
            [{"page": f.page, "method": "drawing_check"}],
            severity=SEVERITY.get(f.rule_id) if f.severity not in SEVERITY_LEVELS else f.severity,  # type: ignore[arg-type]
        )
        for f in ctx.drawing_findings
        if f.rule_id == rule_id
    ]


@rule("SCALE_DISAGREEMENT")
def scale_disagreement(ctx: RuleContext) -> list[DeviationDraft]:
    """Skalmetoderna skiljer mer än 1 % (eller skalan kunde inte bestämmas) – sidan blockeras."""
    return _from_findings(ctx, "SCALE_DISAGREEMENT")


@rule("UNASSIGNED_PIPE")
def unassigned_pipe(ctx: RuleContext) -> list[DeviationDraft]:
    """Otilldelad rörlängd över gränsen på en sida."""
    return _from_findings(ctx, "UNASSIGNED_PIPE")


@rule("UNKNOWN_LABEL_TOKEN")
def unknown_label_token(ctx: RuleContext) -> list[DeviationDraft]:
    """Etikett med en kod som varken legenden eller standardtabellen känner – tolkas inte."""
    return _from_findings(ctx, "UNKNOWN_LABEL_TOKEN")


@rule("MATERIAL_UNRESOLVED")
def material_unresolved(ctx: RuleContext) -> list[DeviationDraft]:
    """Mängdrad utan material där systemet har flera material i projektet."""
    return [
        DeviationDraft(
            "MATERIAL_UNRESOLVED",
            f"{row}: material saknas och systemet har flera material.",
            question=f"Vilket material gäller för {row}?",
        )
        for row, flag in ctx.quantity_flags
        if flag == "MATERIAL_UNRESOLVED"
    ]


MATERIAL_TOKEN_RE = re.compile(r"^[A-Z]{1,2}\d{1,2}$")


def _base(designation: str) -> tuple[str, str | None]:
    """System och material ur en rörbeteckning (`KV01-E13-40` → KV01, E13): materialet är ledet efter systemet
    när det har materialkodens form (bokstav + siffror), också när koden saknas i standardtabellen."""
    parts = designation.upper().split("-")
    mat = parts[1] if len(parts) > 1 and MATERIAL_TOKEN_RE.match(parts[1]) else None
    return parts[0], mat


@rule("MATERIAL_CODE_MISMATCH")
def material_code_mismatch(ctx: RuleContext) -> list[DeviationDraft]:
    """TB:ns rörbeteckning har ett material som ritningen inte använder för systemet (KV01-E9 mot
    KV01-E13)."""
    if ctx.tb is None or not ctx.drawing_pipe_labels:
        return []
    drawn: dict[str, set[str]] = defaultdict(set)
    for lab in ctx.drawing_pipe_labels:
        system, mat = _base(lab)
        if mat:
            drawn[system].add(mat)
    out = []
    for it in ctx.tb.items:
        if it.kind != "pipe" or not it.designation:
            continue
        system, mat = _base(it.designation)
        if mat and system in drawn and mat not in drawn[system]:
            seen = ", ".join(sorted(drawn[system]))
            out.append(
                DeviationDraft(
                    "MATERIAL_CODE_MISMATCH",
                    f"TB anger {it.designation}, ritningarna använder {system}-{seen}.",
                    it.source_refs,
                    question=f"TB anger {it.designation} men ritningen {system}-{seen}. "
                    f"Vilket material gäller?",
                )
            )
    return out


@rule("TB_QTY_VS_DRAWING")
def tb_qty_vs_drawing(ctx: RuleContext) -> list[DeviationDraft]:
    """Antal i TB skiljer från antalet beteckningar/symboler på planerna."""
    if ctx.tb is None or not ctx.drawing_tags:
        return []
    out = []
    for it in ctx.tb.items:
        if it.kind != "object" or it.quantity_mode != "fixed" or it.quantity is None or not it.designation:
            continue
        drawn = ctx.drawing_tags.get(it.designation)
        if drawn is not None and drawn != int(it.quantity):
            out.append(
                DeviationDraft(
                    "TB_QTY_VS_DRAWING",
                    f"{it.designation}: {int(it.quantity)} st i TB, {drawn} på planerna.",
                    it.source_refs,
                    question=f"TB anger {int(it.quantity)} st {it.designation}, planerna "
                    f"visar {drawn}. Vilket gäller?",
                )
            )
    return out


@rule("DRAWING_ITEM_NOT_IN_TB")
def drawing_item_not_in_tb(ctx: RuleContext) -> list[DeviationDraft]:
    """En objektbeteckning på ritningen som saknar post i TB."""
    if ctx.tb is None or not ctx.drawing_tags:
        return []
    known = {it.designation for it in ctx.tb.items if it.designation}
    # bara objektfamiljer som TB själv använder (B…, TS…, AV…): andra disciplinernas taggar på samma blad
    # (brandklass, ventilation, el) är inte VS-poster som saknas
    families = {re.match(r"[A-ZÅÄÖ]+", k).group(0) for k in known if re.match(r"[A-ZÅÄÖ]+", k)}  # type: ignore[union-attr]
    obj = re.compile(load_label_grammar().object.pattern)
    out = []
    for tag, n in sorted(ctx.drawing_tags.items()):
        fam = re.match(r"[A-ZÅÄÖ]+", tag)
        if fam is None or fam.group(0) not in families:
            continue
        if obj.fullmatch(tag) and tag not in known and not any(tag.startswith(k) for k in known if k):
            out.append(
                DeviationDraft(
                    "DRAWING_ITEM_NOT_IN_TB",
                    f"{tag} finns på planerna ({n} st) men har ingen post i TB.",
                    question=f"Ritningen visar {tag} ({n} st) men TB beskriver den inte. "
                    f"Vilken produkt avses?",
                )
            )
    return out


@rule("ACCESSORY_NOT_CONFIRMED")
def accessory_not_confirmed(ctx: RuleContext) -> list[DeviationDraft]:
    """TB kräver tillbehör som den matchade artikeln inte bekräftar (fas 4) – raden blir prisförfrågan."""
    return [
        DeviationDraft(
            "ACCESSORY_NOT_CONFIRMED",
            f"{a.designation} mot artikel {a.article}: {', '.join(a.missing)} bekräftas inte.",
            a.refs,
            question=f"Ingår {', '.join(a.missing)} i {a.article} ({a.designation})?",
        )
        for a in ctx.accessories
        if a.missing
    ]
