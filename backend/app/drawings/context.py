"""Ritningsmängden som underlag för regelmotorn och symbolräkningen (SPEC 6.4, 6.5, fas 6–8).

- Taggar (objektbeteckningar) räknas per plan och tas som största antalet på något planblad: samma brunn visas
på
  flera plan (plan 1 och plan 0 i mark), men två brunnar med samma beteckning på samma blad är två.
- Schemats ventiler och apparater räknas för sig (summa över schemablad).
- Rörbeteckningar, granskningsfynd (skala, otilldelat, okända suffix) och mängdradernas flaggor går till
  RuleContext. Demonteringsblad (fas 1, `purpose:demolition`) mängdas inte.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from app.classify.patterns import ScaleRatio
from app.config.settings import load_label_grammar, load_reference_tables
from app.drawings.checks import Finding, check_takeoff
from app.drawings.source import DrawingTakeoff


@dataclass
class DrawingContext:
    plan_tags: dict[str, int]
    schematic_tags: dict[str, int]
    pipe_labels: list[str]
    findings: list[Finding]
    skipped_pages: list[int] = field(default_factory=list)


def _base_tag(tag: str) -> str:
    """`SIL101-25` → `SIL101`: ett objekts beteckning utan anslutningsdimension."""
    return re.sub(r"-\d{1,3}$", "", tag.strip().upper())


def drawing_context(
    takeoff: DrawingTakeoff,
    plan_pages: set[int],
    schematic_pages: set[int],
    declared_scales: dict[int, ScaleRatio | None] | None = None,
    skip_pages: set[int] | None = None,
) -> DrawingContext:
    obj = re.compile(load_label_grammar().object.pattern)
    plan: Counter[str] = Counter()
    schema: Counter[str] = Counter()
    labels: list[str] = []
    skip = set(skip_pages or ())
    for sheet in takeoff.sheets:
        if sheet.page in skip:
            continue
        tags = Counter(s.tag or "" for s in sheet.symbols if s.kind == "tag" and s.tag)
        if sheet.page in plan_pages:
            for tag, n in tags.items():
                if obj.fullmatch(tag):
                    plan[_base_tag(tag)] = max(plan[_base_tag(tag)], n)
            labels += [r.designation for r in sheet.pipe_runs]
        elif sheet.page in schematic_pages:
            schema.update(Counter({_base_tag(t): n for t, n in tags.items()}))
    standard = set(load_reference_tables().materials) | set(load_reference_tables().systems)
    findings = check_takeoff(
        takeoff,
        declared_scales or {},
        standard,
        skip_pages=skip | schematic_pages | {s.page for s in takeoff.sheets if s.page not in plan_pages},
    )
    return DrawingContext(dict(plan), dict(schema), sorted(set(labels)), findings, sorted(skip))
