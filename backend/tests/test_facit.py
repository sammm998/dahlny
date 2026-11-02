"""Facit för Bilaga A är giltigt, komplett enligt SPEC och konsistent med grammatiken."""

from __future__ import annotations

import re
import runpy
from pathlib import Path

import pytest

from app.config.settings import load_label_grammar
from app.evaluation.facit import ProjectFacit, load_facit, load_manifest

REPO = Path(__file__).resolve().parents[2]
PROJECT = REPO / "eval" / "projects" / "arjang_tvatthall"


@pytest.fixture(scope="module")
def facit() -> ProjectFacit:
    return load_facit(PROJECT / "expected")


def test_spec_items_match_appendix_a1(facit: ProjectFacit) -> None:
    items = facit.spec_items.items
    numbered = [i for i in items if i.ref.isdigit()]
    assert [int(i.ref) for i in numbered] == list(range(1, 29))
    by_ref = {i.ref: i for i in items}
    assert by_ref["4"].rsk == "7606418"
    assert by_ref["5"].parent_designation == "TS101" and by_ref["5"].article_no == "8060-0000"
    assert by_ref["21"].quantity_mode == "per_drawing"
    assert by_ref["26"].quantity_mode == "range" and by_ref["26"].quantity_range == (1, 2)
    ballofix = sum(i.quantity or 0 for i in items if "Ballofix" in i.product)
    assert ballofix == facit.spec_items.aggregates["ballofix_total_st"] == 9


def test_children_reference_existing_parents(facit: ProjectFacit) -> None:
    designations = {i.designation for i in facit.spec_items.items if i.designation}
    for item in facit.spec_items.items:
        if item.parent_designation:
            assert item.parent_designation in designations


def test_deviations_cover_appendix_a3(facit: ProjectFacit) -> None:
    devs = facit.deviations.deviations
    assert sorted({d.number for d in devs}) == list(range(1, 13))
    assert len({d.id for d in devs}) == len(devs)
    rule = {d.number: d.rule_id for d in devs}
    assert rule[1] == "TB_MENTIONED_NOT_ITEMIZED" and rule[5] == "MATERIAL_CODE_MISMATCH"
    # SPEC 13: fas 3 ska hitta 1–4 och 7–9 (1 hittas redan i fas 2), fas 8 ska hitta 5–6.
    assert all(d.expected_by_phase <= 3 for d in devs if d.number in {1, 2, 3, 4, 7, 8, 9})
    assert {d.expected_by_phase for d in devs if d.number in {5, 6}} == {8}


def test_labels_match_appendix_a4(facit: ProjectFacit) -> None:
    counts = {d.drawing_no: len(d.labels) for d in facit.labels.drawings}
    assert counts == {"W-50-1-1000": 42, "W-53-1-0900": 28, "W-50-8-1000": 18}
    unknown = {
        lab.text for d in facit.labels.drawings for lab in d.labels if lab.parse_status == "unknown_token"
    }
    assert unknown == {"KV01-K1-15-W40", "KV01-K1-28-W40", "KV01-K1-W40", "VV01-K1-15-F", "KV01-K1-15-W"}


def test_label_kinds_agree_with_grammar(facit: ProjectFacit) -> None:
    patterns = load_label_grammar().all_patterns()
    kind_to_pattern = {
        "pipe": patterns["pipe"],
        "object": patterns["object"],
        "schematic_valve": patterns["schematic_valve"],
        "height_cl": patterns["height.cl"],
        "height_vg": patterns["height.vg"],
        "slope": patterns["slope"],
        "dimension": r"^\d{1,3}L?$",
    }
    for drawing in facit.labels.drawings:
        for label in drawing.labels:
            pattern = kind_to_pattern.get(label.kind)
            if pattern is not None:
                assert re.match(pattern, label.text), f"{drawing.drawing_no}: {label.text!r} ≠ {label.kind}"


def test_symbols_match_appendix_a5(facit: ProjectFacit) -> None:
    by_tag = {c.tag: c.count for c in facit.symbols.counts}
    assert by_tag["B101P"] == 2 and by_tag["TRYCKLUFTSUTTAG"] == 4 and by_tag["AV15"] == 4
    assert facit.symbols.legend_tables == ["RÖRBETECKNINGAR", "FÖRKLARINGAR", "MATRIS FÖR ISOLERING"]


def test_manifest_lists_confidential_inputs() -> None:
    manifest = load_manifest(PROJECT / "input")
    assert manifest.confidential is True
    assert {f.filename for f in manifest.files} >= {
        "11_5_Teknisk_Beskrivning_VS.pdf",
        "12_4_Ritningar_VS.pdf",
    }


def test_run_eval_reads_facit(tmp_path: Path) -> None:
    module = runpy.run_path(str(REPO / "eval" / "run_eval.py"))
    report = tmp_path / "eval.md"
    assert module["main"](["--report", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    assert "arjang_tvatthall" in text and "ej mätt (fas 2)" in text
