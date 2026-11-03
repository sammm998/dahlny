"""Uppskattningar ur mängden: rördelar (böjar) och isolering (SPEC 6.4.3 l, A.2).

- **Böjar:** en riktningsändring större än `graph.direction_change_deg_fitting` längs ett rörs ritade
polylinje.
  Det är en uppskattning (rördelar ritas inte alltid), och raden säger det.
- **Isolering:** för varje mängdrad det TB-krav (ProjectRule, kategori isolering) som nämner radens system,
och
  isoleringsserien ur ritningens MATRIS FÖR ISOLERING för systemets medium (KV, VV …). Står i TB att
  kopplingsledningar inte isoleras inom rummet de betjänar flaggas raden: längden innehåller dem.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.config.settings import load_thresholds
from app.drawings.legend_tables import LegendTable
from app.drawings.quantities import QuantityRow
from app.tb.extract import RuleDraft


@dataclass
class FittingEstimate:
    identity: str
    bends: int
    method: str = "riktningsändring i ritad polylinje (uppskattning)"


def bends_in(points: list[list[float]], min_deg: float) -> int:
    n = 0
    for a, b, c in zip(points, points[1:], points[2:], strict=False):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cos)) > min_deg:
            n += 1
    return n


def fittings(physical_pipes: list[dict[str, object]]) -> list[FittingEstimate]:
    min_deg = float(load_thresholds().get("graph.direction_change_deg_fitting"))
    by: dict[str, int] = {}
    for p in physical_pipes:
        ident = str(p.get("identity") or "")
        geom = p.get("geometry") or []
        assert isinstance(geom, list)
        by[ident] = by.get(ident, 0) + sum(bends_in(pl, min_deg) for pl in geom)
    return [FittingEstimate(k, v) for k, v in sorted(by.items()) if k]


@dataclass
class InsulationRow:
    system: str
    dim: str | None
    length_m: float
    requirement: str | None  # TB-kravet ordagrant
    series: str | None  # ur MATRIS FÖR ISOLERING
    flags: list[str] = field(default_factory=list)


def _medium(system: str) -> str:
    m = re.match(r"[A-ZÅÄÖ]+", system.upper())
    return m.group(0) if m else system


def insulation(
    rows: list[QuantityRow], rules: list[RuleDraft], tables: list[LegendTable]
) -> list[InsulationRow]:
    ins_rules = [r for r in rules if r.category.lower().startswith("isoler")]
    matrix = next((t for t in tables if "ISOLERING" in t.title.upper()), None)
    connection_rule = next(
        (r for r in ins_rules if "kopplingsledning" in f"{r.text} {r.quote}".lower()), None
    )
    out = []
    for row in rows:
        sys_ = row.system
        req = next(
            (r for r in ins_rules if sys_ in r.applies_to or re.search(rf"\b{re.escape(sys_)}\b", r.quote)),
            None,
        )
        series = None
        if matrix is not None:
            for cells in matrix.rows:
                media = [m.strip().upper() for m in re.split(r"[,/]", cells[0] or "")]
                if _medium(sys_) in media and len(cells) > 1:
                    series = cells[1]
        if req is None and series is None:
            continue
        flags = []
        if connection_rule is not None:
            flags.append(
                "längden innehåller kopplingsledningar som enligt TB inte isoleras inom rummet – granska"
            )
        if req is None:
            flags.append("inget TB-krav för systemet – serien ur ritningens matris")
        out.append(InsulationRow(sys_, row.dim, row.length_m, req.quote if req else None, series, flags))
    return out
