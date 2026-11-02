"""Mätning av fas 1 mot facit (pages.json): sidtyp, ritningsnummer, skala, uppdragsnummer, förteckning och
förväntade avvikelser. Används av `make eval` (SPEC 11, fas 1 DoD)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.classify.patterns import scale_ratios
from app.evaluation.facit import PagesFacit
from app.pipeline.phase1 import Phase1Result


@dataclass
class Check:
    name: str
    ok: bool
    expected: object
    got: object


@dataclass
class Phase1Score:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(c.ok for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)


def _scales(text: str | None) -> list[str]:
    return [s.text for s in scale_ratios(text or "")]


def score_phase1(result: Phase1Result, facit: PagesFacit) -> Phase1Score:
    score = Phase1Score()
    docs = {d.file.filename.rsplit("/", 1)[-1]: d for d in result.documents}
    for exp in facit.documents:
        doc = docs.get(exp.filename)
        got_kind = doc.kind if doc else "saknas"
        score.checks.append(Check(f"{exp.filename}: dokumenttyp", got_kind == exp.kind, exp.kind, got_kind))
        if exp.project_no:
            got = doc.project_no if doc else None
            score.checks.append(
                Check(f"{exp.filename}: uppdragsnr", got == exp.project_no, exp.project_no, got)
            )
    for exp_page in facit.pages:
        doc = docs.get(exp_page.filename)
        page = next((p for p in doc.pages if p.page_no == exp_page.page_no), None) if doc else None
        where = f"{exp_page.filename} s{exp_page.page_no}"
        if page is None:
            score.checks.append(Check(f"{where}: finns", False, "sida", "saknas"))
            continue
        score.checks.append(
            Check(f"{where}: sidtyp", page.kind.kind == exp_page.kind, exp_page.kind, page.kind.kind)
        )
        score.checks.append(
            Check(f"{where}: format", page.format == exp_page.format, exp_page.format, page.format)
        )
        tb = page.title_block
        if exp_page.drawing_no:
            got_no = tb.drawing_no if tb else None
            want_no = exp_page.drawing_no
            score.checks.append(Check(f"{where}: ritningsnr", got_no == want_no, want_no, got_no))
        if exp_page.scale_text and exp_page.drawing_no:
            got_scales = [s.text for s in tb.scales] if tb else []
            want = _scales(exp_page.scale_text)
            score.checks.append(Check(f"{where}: skala", got_scales == want, want, got_scales))
        if exp_page.project_no and exp_page.drawing_no:
            got_project = tb.project_no if tb else None
            score.checks.append(Check(f"{where}: uppdragsnr", got_project == exp_page.project_no,
                                      exp_page.project_no, got_project))  # fmt: skip
    lists = [p.drawing_list for d in result.documents for p in d.pages if p.drawing_list]
    got_rows = [(e.drawing_no, e.title, e.scale_text) for lst in lists for e in lst.drawings]
    want_rows = [(e.drawing_no, e.title, e.scale_text) for e in facit.drawing_list.drawings]
    score.checks.append(Check("ritningsförteckning: rader", got_rows == want_rows, want_rows, got_rows))
    for exp_dev in facit.expected_phase1_deviations:
        pages = set(exp_dev.pages)
        found = [
            d
            for d in result.deviations
            if d.rule_id == exp_dev.rule_id and {r.get("page") for r in d.refs} & pages
        ]
        got_messages: object = [d.message for d in found] or "hittades inte"
        name = f"avvikelse {exp_dev.rule_id}: {exp_dev.subject}"
        score.checks.append(Check(name, bool(found), exp_dev.note, got_messages))
    return score
