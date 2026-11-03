"""Mätning av artikelmatchningen (fas 4) mot expected/matching.json och TESTDATA-registret.

Rätt utfall = samma utfall (stock/virtual/request) och, där facit anger artikel, samma artikel. `uncertain`
räknas
som "osäker" (tillåtet enligt SPEC 11.2 så länge rätt utfall ≥ 95 %), allt annat som fel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.articles.match import MatchResult
from app.tb.extract import ItemDraft


@dataclass
class MatchCheck:
    ref: str
    key: str
    expected: str
    expected_article: str | None
    got: str
    got_article: str | None
    method: str
    score: float
    verdict: str  # ok | osäker | fel | saknas
    rsk: bool


def score_matching(
    results: list[MatchResult], matched: dict[str, ItemDraft], expected_dir: Path
) -> list[MatchCheck]:
    facit = json.loads((expected_dir / "matching.json").read_text(encoding="utf-8"))["expected"]
    by_item = {r.input.key: r for r in results}
    from app.articles.pipeline import match_input

    out = []
    for f in facit:
        it = matched.get(f["ref"])
        r = by_item.get(match_input(it).key) if it is not None else None
        if r is None:
            out.append(
                MatchCheck(
                    f["ref"],
                    "–",
                    f["outcome"],
                    f.get("article"),
                    "–",
                    None,
                    "–",
                    0.0,
                    "saknas",
                    bool(f.get("rsk")),
                )
            )
            continue
        art = r.article.dahl_art_no if r.article else None
        if r.outcome == "uncertain":
            verdict = "osäker"
        elif r.outcome == f["outcome"] and (f.get("article") is None or f.get("article") == art):
            verdict = "ok"
        else:
            verdict = "fel"
        out.append(
            MatchCheck(
                f["ref"],
                r.input.key,
                f["outcome"],
                f.get("article"),
                r.outcome,
                art,
                r.method,
                r.score,
                verdict,
                bool(f.get("rsk")),
            )
        )
    return out


def report_lines(checks: list[MatchCheck]) -> list[str]:
    ok = sum(c.verdict == "ok" for c in checks)
    unsure = sum(c.verdict == "osäker" for c in checks)
    rsk = [c for c in checks if c.rsk]
    lines = [
        f"### Fas 4 – artikelmatchning (TESTDATA-register): {ok}/{len(checks)} rätt, {unsure} osäkra",
        "",
        f"Rader med RSK: {sum(c.verdict == 'ok' for c in rsk)}/{len(rsk)} rätt utfall (DoD: alla).",
        "",
        "| Ref | Post | Facit | Fick | Artikel facit/fick | Metod | Score | Bedömning |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in checks:
        lines.append(
            f"| {c.ref} | {c.key[:40]} | {c.expected} | {c.got} | {c.expected_article or '–'}/"
            f"{c.got_article or '–'} | {c.method} | {c.score:.2f} | {c.verdict} |"
        )
    return lines
