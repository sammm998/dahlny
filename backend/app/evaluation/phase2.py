"""Mätning av fas 2 mot facit (spec_items.json, project_rules.json): SPEC 11.2 TB-måtten och fas 2 DoD.

Matchning: en huvudpost mot facit på beteckning; en barnpost mot facit under samma huvudpost på RSK, art.nr
eller
ordlikhet i produktnamnet. Facitets rörrad ("rör") räknas som hittad om extraktionen har minst en rörpost;
rörposter
räknas aldrig som påhittade (facit sammanfattar dem i en rad). En extraherad post som inte matchar något i
facit är
påhittad.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.tb.extract import ItemDraft, TBResult

WORD_RE = re.compile(r"[a-zåäö0-9]{3,}")
CHILD_SIMILARITY_MIN = 0.15
RULE_KEY_SHARE = 0.7  # så stor del av facitkravets ordstammar ska finnas i ett extraherat krav


@dataclass
class ItemCheck:
    ref: str
    designation: str
    found: bool
    rsk_ok: bool | None = None
    art_ok: bool | None = None
    qty_ok: bool | None = None
    mode_ok: bool | None = None
    got: dict[str, Any] = field(default_factory=dict)


@dataclass
class Phase2Score:
    checks: list[ItemCheck]
    fabricated: list[str]
    golvranna_found: bool
    rules_found: list[tuple[str, bool]]
    flags: list[str]
    matched: dict[str, ItemDraft] = field(default_factory=dict)  # facitradens ref → extraherad post

    @property
    def recall(self) -> float:
        return sum(c.found for c in self.checks) / len(self.checks) if self.checks else 0.0

    @property
    def precision(self) -> float:
        found = sum(c.found for c in self.checks)
        return found / (found + len(self.fabricated)) if found + len(self.fabricated) else 0.0

    def share(self, attr: str) -> tuple[int, int]:
        vals = [getattr(c, attr) for c in self.checks if c.found and getattr(c, attr) is not None]
        return sum(vals), len(vals)


def _norm(v: str | None) -> str:
    return re.sub(r"\s+", "", v or "").upper()


def _words(text: str) -> set[str]:
    return set(WORD_RE.findall(text.lower()))


def _similar(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def _qty(f: dict[str, Any], it: ItemDraft) -> bool:
    if f["quantity_mode"] == "range":
        lo, hi = f["quantity_range"]
        return it.quantity_min == Decimal(lo) and it.quantity_max == Decimal(hi)
    if f["quantity"] is None:
        return it.quantity is None
    return it.quantity == Decimal(str(f["quantity"]))


def _check(f: dict[str, Any], it: ItemDraft | None) -> ItemCheck:
    c = ItemCheck(f["ref"], f["designation"] or f"({f['parent_designation']})", it is not None)
    if it is None:
        return c
    c.rsk_ok = _norm(it.rsk) == _norm(f["rsk"])
    c.art_ok = _norm(it.article_no) == _norm(f["article_no"]) if f["article_no"] else None
    c.qty_ok = _qty(f, it)
    c.mode_ok = it.quantity_mode == f["quantity_mode"]
    c.got = {
        "rsk": it.rsk,
        "article_no": it.article_no,
        "quantity": str(it.quantity),
        "mode": it.quantity_mode,
        "description": it.description,
    }
    return c


def score_phase2(result: TBResult, expected_dir: Path) -> Phase2Score:
    facit = json.loads((expected_dir / "spec_items.json").read_text(encoding="utf-8"))["items"]
    rules_facit = json.loads((expected_dir / "project_rules.json").read_text(encoding="utf-8"))["rules"]
    parents = {it.designation: it for it in result.items if it.kind == "object"}
    used: set[int] = set()
    matched: dict[str, ItemDraft] = {}
    checks: list[ItemCheck] = []
    for f in facit:
        if f["ref"] == "rör":
            pipes = [it for it in result.items if it.kind == "pipe"]
            checks.append(ItemCheck("rör", "Rör", bool(pipes), got={"pipes": [p.designation for p in pipes]}))
            continue
        if f["parent_designation"] is None:
            it = parents.get(f["designation"])
            if it is not None:
                used.add(id(it))
                matched[f["ref"]] = it
            checks.append(_check(f, it))
            continue
        parent = parents.get(f["parent_designation"])
        best: tuple[float, ItemDraft] | None = None
        for ch in parent.children if parent else []:
            if id(ch) in used:
                continue
            if (f["rsk"] and _norm(ch.rsk) == _norm(f["rsk"])) or (
                f["article_no"] and _norm(ch.article_no) == _norm(f["article_no"])
            ):
                score = 2.0
            else:
                score = _similar(f["product"], f"{ch.description} {ch.model or ''} {ch.manufacturer or ''}")
            if score >= CHILD_SIMILARITY_MIN and (best is None or score > best[0]):
                best = (score, ch)
        if best:
            used.add(id(best[1]))
            matched[f["ref"]] = best[1]
        checks.append(_check(f, best[1] if best else None))
    fabricated = [
        f"{x.parent_designation + ' > ' if x.parent_designation else ''}{x.designation or x.description}"
        for x in result.all_items()
        if x.kind == "object" and id(x) not in used
    ]
    golv = any(
        d.rule_id == "TB_MENTIONED_NOT_ITEMIZED" and "golvränn" in d.message.lower()
        for d in result.deviations
    )
    rules_found = []
    for r in rules_facit:
        # ordstammar (6 tecken) ur facitkravets längre ord; ett extraherat krav som bär alla träffar
        keys = {w[:6] for w in _words(r["text"]) if len(w) > 4}
        hit = any(
            keys and len(keys & {w[:6] for w in _words(f"{x.text} {x.quote}")}) >= RULE_KEY_SHARE * len(keys)
            for x in result.rules
        )
        rules_found.append((r["text"], hit))
    return Phase2Score(checks, fabricated, golv, rules_found, result.flags, matched)


def report_lines(score: Phase2Score) -> list[str]:
    found = sum(c.found for c in score.checks)
    lines = [
        f"### Fas 2 – TB-extraktion ({found}/{len(score.checks)} facitrader hittade)",
        "",
        "| Mått | Gräns | Resultat |",
        "| --- | --- | --- |",
        f"| Recall sakvaror | ≥ 98 % | {100 * score.recall:.1f} % |",
        f"| Precision (påhittade rader) | ≥ 99 % | {100 * score.precision:.1f} % "
        f"({len(score.fabricated)} påhittade) |",
    ]
    for attr, name in (
        ("rsk_ok", "RSK exakt"),
        ("art_ok", "Art.nr exakt"),
        ("qty_ok", "Antal"),
        ("mode_ok", "quantity_mode"),
    ):
        ok, n = score.share(attr)
        limit = "100 %" if attr in ("rsk_ok", "art_ok") else "≥ 99 %"
        lines.append(f"| {name} | {limit} | {ok}/{n} |")
    lines.append(f"| Golvränneavvikelsen (A.3 nr 1) | hittas | {'ja' if score.golvranna_found else 'NEJ'} |")
    ok_rules = sum(ok for _, ok in score.rules_found)
    lines.append(f"| Generella krav (A.2) | – | {ok_rules}/{len(score.rules_found)} |")
    lines += [
        "",
        "| # | Beteckning | Hittad | RSK | Art.nr | Antal | Läge | Fick |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    yn = {True: "ok", False: "FEL", None: "–"}
    for c in score.checks:
        lines.append(
            f"| {c.ref} | {c.designation} | {yn[c.found]} | {yn[c.rsk_ok]} | {yn[c.art_ok]} | "
            f"{yn[c.qty_ok]} | {yn[c.mode_ok]} | {json.dumps(c.got, ensure_ascii=False)[:120]} |"
        )
    if score.fabricated:
        lines += ["", "Poster utan motsvarighet i facit: " + ", ".join(score.fabricated)]
    missing_rules = [t for t, ok in score.rules_found if not ok]
    if missing_rules:
        lines += ["", "Generella krav som inte hittades: " + "; ".join(missing_rules)]
    if score.flags:
        lines += ["", "Flaggor: " + "; ".join(score.flags[:20])]
    return lines
