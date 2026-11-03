"""Rördelar (böjar) och isolering ur mängden (SPEC 6.4.3 l, A.2)."""

from __future__ import annotations

from app.drawings.estimates import bends_in, fittings, insulation
from app.drawings.legend_tables import LegendTable
from app.drawings.quantities import QuantityRow
from app.tb.extract import RuleDraft


def test_a_bend_is_a_direction_change_over_the_threshold() -> None:
    assert bends_in([[0, 0], [100, 0], [100, 100]], 30) == 1  # 90°
    assert bends_in([[0, 0], [100, 0], [200, 10]], 30) == 0  # 6° – rak ledning med knyck
    assert (
        fittings([{"identity": "KV01|DN15", "geometry": [[[0, 0], [10, 0], [10, 10], [20, 10]]]}])[0].bends
        == 2
    )


def row(system: str, dim: str, m: float) -> QuantityRow:
    return QuantityRow(
        system=system,
        material="K1",
        material_source="etikett",
        material_confidence=None,
        dim=dim,
        length_m=m,
        ambiguous_m=0.0,
        pages=[2],
        sub_rows=[],
    )


def test_insulation_takes_the_tb_requirement_and_the_drawing_matrix() -> None:
    rules = [
        RuleDraft("isolering", "KV01 30 mm", "KV01 isoleras med diffusionstät rörskål 30mm.", ["KV01"], []),
        RuleDraft(
            "isolering",
            "kopplingsledningar",
            "Kopplingsledningar för tappvatten isoleras ej inom det rum de betjänar.",
            [],
            [],
        ),
    ]
    matrix = LegendTable(
        2,
        "MATRIS FÖR ISOLERING",
        ["RÖRSYSTEM", "SERIE"],
        [["KV", "A+DIFF.SPÄRR"], ["VV, VVC, VS", "A, B el. C"]],
        [],
        (0, 0, 1, 1),
    )
    got = insulation(
        [row("KV01", "15", 12.0), row("VV01", "15", 8.0), row("S01", "110", 5.0)], rules, [matrix]
    )
    kv, vv = got
    assert (kv.system, kv.requirement, kv.series) == (
        "KV01",
        "KV01 isoleras med diffusionstät rörskål 30mm.",
        "A+DIFF.SPÄRR",
    )
    assert (
        vv.requirement is None and vv.series == "A, B el. C" and any("inget TB-krav" in f for f in vv.flags)
    )
    assert any("kopplingsledningar" in f for f in kv.flags)  # S01 har varken krav eller serie: ingen rad
