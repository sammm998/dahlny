"""Mätning av avvikelserna mot facit (deviations.json, SPEC 15 A.3).

En facitavvikelse räknas som hittad när motorn gav en avvikelse med samma regel-id vars meddelande bär alla
ord
ur facitets `subject` (ordstammar om sex tecken, så att "snabbkopplingstyp" hittar "typ av snabbkoppling").
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.rules.catalog import DeviationDraft

STEM = 6


@dataclass
class DeviationCheck:
    id: str
    rule_id: str
    subject: str
    phase: int
    found: bool
    message: str | None


def _stems(text: str) -> set[str]:
    return {w[:STEM] for w in re.findall(r"[a-zåäö0-9.\-]{3,}", text.lower())}


def score_deviations(got: list[DeviationDraft], expected_dir: Path, max_phase: int) -> list[DeviationCheck]:
    facit = json.loads((expected_dir / "deviations.json").read_text(encoding="utf-8"))["deviations"]
    out = []
    for f in facit:
        if f["expected_by_phase"] > max_phase:
            continue
        keys = {w[:STEM] for w in re.split(r"[\s/]+", f["subject"].lower()) if len(w) >= 3}
        hit = next(
            (
                d
                for d in got
                if d.rule_id == f["rule_id"]
                and all(any(s.startswith(k) or k.startswith(s) for s in _stems(d.message)) for k in keys)
            ),
            None,
        )
        out.append(
            DeviationCheck(
                f["id"],
                f["rule_id"],
                f["subject"],
                f["expected_by_phase"],
                hit is not None,
                hit.message if hit else None,
            )
        )
    return out


def report_lines(
    checks: list[DeviationCheck], got: list[DeviationDraft], title: str = "Fas 3 – avvikelser (A.3)"
) -> list[str]:
    found = sum(c.found for c in checks)
    lines = [
        f"### {title}: {found}/{len(checks)} hittade",
        "",
        "| A.3 | Regel | Ämne | Fas | Hittad | Meddelande |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in checks:
        msg = (c.message or "").replace("|", "/")[:140]
        lines.append(
            f"| {c.id} | {c.rule_id} | {c.subject} | {c.phase} | {'ok' if c.found else '**NEJ**'} | {msg} |"
        )
    by_rule: dict[str, int] = {}
    for d in got:
        by_rule[d.rule_id] = by_rule.get(d.rule_id, 0) + 1
    lines += ["", "Alla avvikelser per regel: " + ", ".join(f"{k} {v}" for k, v in sorted(by_rule.items()))]
    return lines
