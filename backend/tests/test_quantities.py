"""Mängdlista per system × material × dimension, suffix som underrader, material ur systemets enda
material."""

from __future__ import annotations

from app.drawings.quantities import summarize
from app.drawings.source import PipeRunDraft
from app.tb.system_materials import DRAWING, TB, SystemMaterialIndex, from_designations, from_tb_pages

KNOWN = {"K1", "K5", "S13", "P2", "KV", "VV", "L9", "S01"}


def run(designation: str, metres: float, *, system: str, material: str | None, dim: str | None,
        page: int = 1, ambiguous: float = 0.0) -> PipeRunDraft:  # fmt: skip
    return PipeRunDraft(
        page=page, designation=designation, system=system, material=material, dim=dim,
        length_m_horizontal=metres, length_m_vertical=None, length_m_total=metres, ambiguous_m=ambiguous,
        in_hatched_area_m=0.0, riser_count=0, state="CONFIRMED", confidence=0.9, segment_ids=[],
        source_refs=[],
    )  # fmt: skip


TB_TEXT = "PNU.215 Ledningar av raka stålrör  L9-S13  Tryckluft  Enl ritn\nKV01-K1 Tappkallvatten KV01-E9 PEM"


def index(*designations: str) -> SystemMaterialIndex:
    return SystemMaterialIndex.build(
        from_tb_pages([(12, TB_TEXT)]), from_designations((1, d) for d in designations)
    )


def test_tb_and_labels_give_materials_per_system() -> None:
    idx = index("L9-S13-28", "KV01-K1-15-W40")
    assert idx.materials("L9") == {"S13"} and idx.materials("KV01") == {"K1", "E9"}
    assert {sm.source for sm in idx.found if sm.system == "L9"} == {TB, DRAWING}


def test_suffixes_are_summed_under_the_base_and_shown_as_flagged_sub_rows() -> None:
    rows = summarize(
        [run("KV01-K1-15-W40", 3.64, system="KV01", material="K1", dim="15"),
         run("KV01-K1-15-W", 12.36, system="KV01", material="K1", dim="15"),
         run("KV01-K1-15", 0.15, system="KV01", material="K1", dim="15", ambiguous=6.63)],
        known_codes=KNOWN, system_materials=index(),
    )  # fmt: skip
    [row] = rows
    assert row.base == "KV01-K1-15" and row.length_m == 16.15 and row.ambiguous_m == 6.63
    subs = {s.suffix: s for s in row.sub_rows}
    assert set(subs) == {"", "W", "W40"}
    assert subs["W40"].length_m == 3.64 and subs["W40"].flags == ["UNKNOWN_LABEL_TOKEN:W40"]
    assert subs["W"].flags == ["UNKNOWN_LABEL_TOKEN:W"] and subs[""].flags == []
    assert set(row.flags) == {"UNKNOWN_LABEL_TOKEN:W", "UNKNOWN_LABEL_TOKEN:W40"}
    assert row.material_source == "etikett" and row.material_confidence is None


def test_the_air_vent_suffix_after_the_size_is_known() -> None:
    [row] = summarize([run("S01-P2-110L", 2.0, system="S01", material="P2", dim="110L")],
                      known_codes=KNOWN, system_materials=index())  # fmt: skip
    assert row.dim == "110" and [s.suffix for s in row.sub_rows] == ["L"] and row.flags == []


def test_a_system_with_one_material_gets_it_from_tb() -> None:
    rows = summarize([run("L9-22", 5.29, system="L9", material=None, dim="22"),
                      run("L9-S13-22", 5.74, system="L9", material="S13", dim="22")],
                     known_codes=KNOWN, system_materials=index("L9-S13-28"))  # fmt: skip
    [row] = rows
    assert row.material == "S13" and row.length_m == 11.03
    assert row.material_source == "TB+etikett" and row.material_confidence == 0.85
    assert "MATERIAL_FROM_SYSTEM" in row.flags


def test_a_system_with_several_materials_is_left_empty_and_flagged() -> None:
    [row] = summarize([run("KV01-15", 1.0, system="KV01", material=None, dim="15")],
                      known_codes=KNOWN, system_materials=index("KV01-K1-15"))  # fmt: skip
    assert row.material is None and "MATERIAL_UNRESOLVED" in row.flags and row.material_source is None


def test_a_system_no_source_names_a_material_for_is_flagged() -> None:
    [row] = summarize([run("X9-15", 1.0, system="X9", material=None, dim="15")],
                      known_codes=KNOWN, system_materials=index())  # fmt: skip
    assert row.material is None and row.flags == ["MATERIAL_UNRESOLVED"]
