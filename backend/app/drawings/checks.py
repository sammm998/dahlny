"""VS-Kalkyls egna kontroller ovanpå en ritningskällas resultat (SPEC 6.4.3 d, f, h.5; 6.4.7).

Källan (vvs_engine) får inte vara ensam domare över sin egen skala eller sina beteckningar. Kontrollerna
här jämför med det handlingarna själva säger – titelblockets skala och sidans pappersstorlek, projektets
legend – och lämnar avvikelser. De ändrar aldrig källans siffror.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.classify.patterns import ScaleRatio
from app.config.settings import load_label_grammar, load_thresholds
from app.drawings.source import DrawingTakeoff, SheetTakeoff

M_PER_PT_AT_1_1 = 0.0254 / 72  # en PDF-punkt i meter


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str  # info | warning | critical (SPEC 6.5)
    page: int
    message: str
    blocks_page: bool = False


def m_per_pt(denominator: int) -> float:
    return denominator * M_PER_PT_AT_1_1


def declared_scale_for_page(scales: Iterable[ScaleRatio], paper_size: str | None) -> ScaleRatio | None:
    """Titelblockets skala som gäller för sidans egen pappersstorlek (SPEC 6.4.3 f.1).

    '1:50 (A1) 1:100 (A3)' på en A1-sida → 1:50. En enda skala utan pappersangivelse gäller som den står.
    Flera skalor utan att sidans storlek avgör → None (konflikt, inget antas)."""
    scales = list(scales)
    if paper_size:
        matching = [s for s in scales if s.paper == paper_size]
        if len(matching) == 1:
            return matching[0]
    unqualified = [s for s in scales if s.paper is None]
    if len(scales) == 1 and unqualified:
        return scales[0]
    return None


def check_scale(sheet: SheetTakeoff, declared: ScaleRatio | None) -> list[Finding]:
    tol = load_thresholds().get("scale.max_disagreement_fraction")
    if sheet.scale is None or sheet.scale.meters_per_pt is None:
        return [Finding("SCALE_DISAGREEMENT", "critical", sheet.page, "Källan angav ingen skala", True)]
    out = []
    if not sheet.scale.verified:
        out.append(
            Finding(
                "SCALE_DISAGREEMENT",
                "critical",
                sheet.page,
                f"Källans skala är inte verifierad ({sheet.scale.state}: {sheet.scale.reason})",
                True,
            )
        )
    if declared is None:
        out.append(
            Finding(
                "SCALE_DISAGREEMENT",
                "critical",
                sheet.page,
                "Titelblockets skala kunde inte knytas till sidans pappersstorlek – välj skala manuellt",
                True,
            )
        )
        return out
    expected = m_per_pt(declared.denominator)
    diff = abs(sheet.scale.meters_per_pt - expected) / expected
    if diff > tol:
        source_ratio = sheet.scale.meters_per_pt / M_PER_PT_AT_1_1
        out.append(
            Finding(
                "SCALE_DISAGREEMENT",
                "critical",
                sheet.page,
                f"Källan mäter i 1:{source_ratio:.0f} men titelblocket anger {declared.text} för sidans "
                f"format ({diff:.0%} skillnad) – sidan blockeras för mängdning",
                True,
            )
        )
    return out


def check_unassigned(sheet: SheetTakeoff) -> list[Finding]:
    limit = load_thresholds().get("assign.max_unassigned_length_fraction")
    frac = sheet.coverage.unassigned_fraction if sheet.coverage else None
    if frac is None or frac <= limit:
        return []
    return [
        Finding(
            "UNASSIGNED_PIPE",
            "critical",
            sheet.page,
            f"{frac:.0%} av ritad rörlängd är otilldelad eller tvetydig (gräns {limit:.0%})",
            True,
        )
    ]


def check_tokens(sheet: SheetTakeoff, legend_codes: set[str], standard_codes: set[str]) -> list[Finding]:
    """Varje del av en rörbeteckning ska finnas i projektets legend (i första hand) eller standardtabellen."""
    known = legend_codes | standard_codes
    pattern = load_label_grammar().pipe.pattern
    out = []
    for run in sheet.pipe_runs:
        m = re.match(pattern, run.designation)
        if not m:
            out.append(
                Finding(
                    "UNKNOWN_LABEL_TOKEN",
                    "warning",
                    sheet.page,
                    f"{run.designation!r} följer inte grammatiken",
                )
            )
            continue
        system = m.group("system")
        if system not in known and re.sub(r"\d+L?$", "", system) not in known:
            out.append(
                Finding(
                    "UNKNOWN_LABEL_TOKEN",
                    "warning",
                    sheet.page,
                    f"Okänt system {system!r} i {run.designation!r}",
                )
            )
        material = m.group("material")
        if material and material not in known:
            out.append(
                Finding(
                    "UNKNOWN_LABEL_TOKEN",
                    "warning",
                    sheet.page,
                    f"Okänt material {material!r} i {run.designation!r}",
                )
            )
        for suffix in filter(None, (m.group("suffixes") or "").split("-")):
            if suffix not in known:
                out.append(
                    Finding(
                        "UNKNOWN_LABEL_TOKEN",
                        "warning",
                        sheet.page,
                        f"Okänt suffix {suffix!r} i {run.designation!r} – fråga konsulten om betydelsen "
                        "(tolkas inte)",
                    )
                )
    return out


def check_takeoff(
    takeoff: DrawingTakeoff,
    declared_by_page: dict[int, ScaleRatio | None],
    standard_codes: set[str],
    skip_pages: set[int] | None = None,
) -> list[Finding]:
    """Alla kontroller för sidor som ska mängdas (planer). Schema- och förteckningssidor ges i skip_pages."""
    findings: list[Finding] = []
    for sheet in takeoff.sheets:
        if skip_pages and sheet.page in skip_pages:
            continue
        legend = {e.code for e in sheet.legend}
        findings += check_scale(sheet, declared_by_page.get(sheet.page))
        findings += check_unassigned(sheet)
        findings += check_tokens(sheet, legend, standard_codes)
    return findings
