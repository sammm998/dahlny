"""vvs_engine-adaptern (SPEC 6.4.7) och VS-Kalkyls kontroller ovanpå den.

Fixturen är syntetisk – samma form som motorns artefakter (artifact_schema 3), inga verkliga handlingar.
Ett integrationstest kör den riktiga motorn om VVS_ENGINE_CMD är satt och Bilaga A finns lokalt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.classify.patterns import scale_ratios
from app.config.settings import load_reference_tables
from app.drawings.checks import (
    check_scale,
    check_takeoff,
    check_tokens,
    check_unassigned,
    declared_scale_for_page,
    m_per_pt,
)
from app.drawings.source import DrawingSourceError
from app.drawings.vvs_engine import VvsEngineSource

SHA = "a" * 64


def write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def make_artifacts(root: Path, *, meters_per_pt: float = m_per_pt(50), scale_state: str = "VERIFIED") -> Path:
    write(
        root / "freeze-manifest.json",
        {
            "artifact_schema": 3,
            "engine_version": "0.1.0",
            "source_revision": "abcdef1234",
            "input_pdf_sha256": SHA,
        },
    )
    write(
        root / "reading-coverage.json",
        {"sheets": [{"page": 0, "drawn_m": 10.0, "confirmed_m": 9.9, "ambiguous_m": 0.0, "unowned_m": 0.1}]},
    )
    write(root / "summary.json", {"skipped_pages": []})
    sheet = root / "sheets" / "0"
    write(sheet / "page.json", {"page": 0, "width_pt": 2384.0, "height_pt": 1684.0})
    write(
        sheet / "quantities.json",
        {
            "scale": {
                "state": scale_state,
                "meters_per_pdf_point": meters_per_pt,
                "reason": "test",
                "evidence": [],
            },
            "rows": [
                {
                    "designation": "KV01-K1-28",
                    "dn": 28,
                    "system": "KV01",
                    "state": "CONFIRMED",
                    "confirmed_horizontal_m": 7.5,
                    "confirmed_total_m": 7.5,
                    "vertical_m": "UNKNOWN",
                    "vertical_known": False,
                    "ambiguous_m": 0.0,
                    "in_hatched_area_m": 0.0,
                    "riser_count": 1,
                    "pipe_ids": ["pp_1"],
                },
                {
                    "designation": "KV01-K1-15-W40",
                    "dn": 15,
                    "state": "AMBIGUOUS",
                    "confirmed_horizontal_m": 0.0,
                    "ambiguous_m": 2.4,
                    "pipe_ids": ["pp_2"],
                },
            ],
            "risers": {
                "KV01-K1|DN28": [{"designation": "KV01-K1-28", "point": [100.0, 200.0], "source": "label"}]
            },
        },
    )
    write(
        sheet / "physical-pipes.json",
        {
            "physical_pipes": [
                {
                    "physical_pipe_id": "pp_1",
                    "identity": "KV01-K1-28|DN28",
                    "geometry": [[[10.0, 20.0], [400.0, 20.0]]],
                    "source_path_ids": ["path_a", "path_b"],
                    "supporting_anchors": ["anc_1"],
                    "evidence_state": "CONFIRMED",
                    "evidence": ["chain_from_anchor"],
                    "frontier_reasons": ["SYMBOL"],
                    "confidence_tier": "verified",
                    "needs_review": False,
                },
                {
                    "physical_pipe_id": "pp_2",
                    "geometry": [[[10.0, 50.0], [80.0, 50.0]]],
                    "confidence_tier": "mystery",
                    "needs_review": True,
                },
            ]
        },
    )
    write(
        sheet / "vector-designations.json",
        {
            "designations": [
                {"did": "d1", "text": "B201B", "bbox": [1, 2, 3, 4], "min_glyph_confidence": 0.95},
                {"did": "d2", "text": "K1", "bbox": [5, 6, 7, 8], "min_glyph_confidence": 0.99},  # legendkod
                {"did": "d3", "text": "KV01-K1-28", "bbox": [9, 9, 9, 9]},
            ]
        },
    )
    write(
        sheet / "drawing-legend.json",
        {"entries": [{"code": "K1", "description": "KOPPAR, HÅRDA", "role": "material"},
                     {"code": "KV", "description": "TAPPKALLVAT?EN", "role": "system"}]},
    )  # fmt: skip
    return root


def test_maps_quantities_to_pipe_run_drafts_with_evidence(tmp_path: Path) -> None:
    takeoff = VvsEngineSource().read_artifacts(make_artifacts(tmp_path), expected_sha256=SHA)
    assert takeoff.source_version == "vvs_engine 0.1.0 @abcdef1"
    [sheet] = takeoff.sheets
    assert sheet.page == 1  # motorns 0-baserade index → handlingens sidnummer
    run, ambiguous = sheet.pipe_runs
    assert (run.system, run.material, run.dim) == ("KV01", "K1", "28")
    assert run.length_m_horizontal == 7.5
    assert run.length_m_vertical is None  # "ej bestämd", aldrig 0
    assert run.confidence == 0.95 and run.flags == []
    [ref] = run.source_refs
    assert ref.method == "vvs_engine" and ref.page == 1
    assert ref.bbox == (10.0, 20.0, 400.0, 20.0)
    assert ref.evidence["source_path_ids"] == ["path_a", "path_b"]
    assert ref.evidence["supporting_anchors"] == ["anc_1"]
    # tvetydigt: konfidens 0, okänd nivå och granskning flaggas, suffixet behålls
    assert ambiguous.confidence == 0.0
    assert {"state:AMBIGUOUS", "needs_review", "unknown_confidence_tier:mystery", "suffix:W40"} <= set(
        ambiguous.flags
    )


def test_symbols_risers_and_tags(tmp_path: Path) -> None:
    [sheet] = VvsEngineSource().read_artifacts(make_artifacts(tmp_path)).sheets
    risers = [s for s in sheet.symbols if s.kind == "riser"]
    tags = [s for s in sheet.symbols if s.kind == "tag"]
    assert [r.tag for r in risers] == ["KV01-K1-28"]
    assert [t.tag for t in tags] == ["B201B"]  # legendkoden K1 och rörbeteckningen räknas inte
    assert "text_occurrence_not_symbol" in tags[0].flags


def test_legend_unreadable_chars_flagged(tmp_path: Path) -> None:
    [sheet] = VvsEngineSource().read_artifacts(make_artifacts(tmp_path)).sheets
    flags = {e.code: e.flags for e in sheet.legend}
    assert flags == {"K1": [], "KV": ["unreadable_chars"]}


def test_rejects_wrong_input_and_unknown_schema(tmp_path: Path) -> None:
    root = make_artifacts(tmp_path)
    with pytest.raises(DrawingSourceError, match="annan fil"):
        VvsEngineSource().read_artifacts(root, expected_sha256="b" * 64)
    manifest = json.loads((root / "freeze-manifest.json").read_text())
    manifest["artifact_schema"] = 99
    write(root / "freeze-manifest.json", manifest)
    with pytest.raises(DrawingSourceError, match="schema 99"):
        VvsEngineSource().read_artifacts(root)


def test_missing_engine_binary_fails_loud(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(DrawingSourceError, match="hittas inte"):
        VvsEngineSource(command=["/finns/inte/vvs-takeoff"]).analyze(pdf, tmp_path)


@pytest.mark.parametrize(
    ("text", "paper", "expected"),
    [
        ("1:50 (A1) 1:100 (A3)", "A1", 50),
        ("1:50 (A1) 1:100 (A3)", "A3", 100),
        ("1:50", "A1", 50),
        ("1:50 (A1) 1:100 (A3)", "A4", None),  # sidans format matchar ingen skala → konflikt
        ("1:50 1:100", "A1", None),
    ],
)
def test_declared_scale_follows_paper_size(text: str, paper: str, expected: int | None) -> None:
    got = declared_scale_for_page(scale_ratios(text), paper)
    assert (got.denominator if got else None) == expected


def test_scale_mismatch_blocks_page(tmp_path: Path) -> None:
    # Bilaga A: motorn valde 1:100 (A3) på ett A1-blad där 1:50 (A1) gäller.
    [sheet] = VvsEngineSource().read_artifacts(make_artifacts(tmp_path, meters_per_pt=m_per_pt(100))).sheets
    [finding] = check_scale(sheet, declared_scale_for_page(scale_ratios("1:50 (A1) 1:100 (A3)"), "A1"))
    assert finding.rule_id == "SCALE_DISAGREEMENT" and finding.blocks_page
    assert "1:100" in finding.message and "1:50 (A1)" in finding.message


def test_matching_verified_scale_passes(tmp_path: Path) -> None:
    [sheet] = VvsEngineSource().read_artifacts(make_artifacts(tmp_path)).sheets
    assert check_scale(sheet, declared_scale_for_page(scale_ratios("1:50 (A1)"), "A1")) == []


def test_unverified_scale_is_critical(tmp_path: Path) -> None:
    [sheet] = VvsEngineSource().read_artifacts(make_artifacts(tmp_path, scale_state="CONFLICT")).sheets
    findings = check_scale(sheet, declared_scale_for_page(scale_ratios("1:50"), "A1"))
    assert [f.rule_id for f in findings] == ["SCALE_DISAGREEMENT"]


def test_unknown_suffix_is_reported_not_dropped(tmp_path: Path) -> None:
    [sheet] = VvsEngineSource().read_artifacts(make_artifacts(tmp_path)).sheets
    rt = load_reference_tables()
    messages = [f.message for f in check_tokens(sheet, {"K1", "KV"}, set(rt.materials) | set(rt.systems))]
    assert messages == ["Okänt suffix 'W40' i 'KV01-K1-15-W40' – fråga konsulten om betydelsen (tolkas inte)"]


def test_check_takeoff_respects_skip_pages(tmp_path: Path) -> None:
    takeoff = VvsEngineSource().read_artifacts(make_artifacts(tmp_path))
    rt = load_reference_tables()
    codes = set(rt.materials) | set(rt.systems)
    decl = {1: declared_scale_for_page(scale_ratios("1:50 (A1)"), "A1")}
    # 1 % otilldelat ligger under gränsen 2 %; bara W40-suffixet återstår
    assert [f.rule_id for f in check_takeoff(takeoff, decl, codes)] == ["UNKNOWN_LABEL_TOKEN"]
    assert check_takeoff(takeoff, decl, codes, skip_pages={1}) == []


def test_unassigned_above_limit_blocks_page(tmp_path: Path) -> None:
    root = make_artifacts(tmp_path)
    write(
        root / "reading-coverage.json",
        {"sheets": [{"page": 0, "drawn_m": 10.0, "confirmed_m": 7.0, "ambiguous_m": 1.0, "unowned_m": 2.0}]},
    )
    [sheet] = VvsEngineSource().read_artifacts(root).sheets
    [finding] = check_unassigned(sheet)
    assert finding.rule_id == "UNASSIGNED_PIPE" and finding.blocks_page and "30%" in finding.message


BILAGA_A = Path(__file__).resolve().parents[2] / "eval/projects/arjang_tvatthall/input/12_4_Ritningar_VS.pdf"


@pytest.mark.skipif(
    not os.environ.get("VVS_ENGINE_CMD") or not BILAGA_A.exists(),
    reason="integrationstest: kräver vvs_engine (VVS_ENGINE_CMD) och Bilaga A lokalt",
)
def test_real_engine_on_bilaga_a_scale(tmp_path: Path) -> None:
    """Med motorns rättelser (Dahlvvvs, 2026-11-02): alla tre ritningsbladen mäts i 1:50, verifierat mot den
    märkta skalstocken 0–1–2–5 METER. VS-Kalkyls oberoende skalkontroll håller med titelblocket."""
    takeoff = VvsEngineSource().analyze(BILAGA_A, tmp_path)
    assert len(takeoff.sheets) == 4
    declared = declared_scale_for_page(scale_ratios("1:50 (A1) 1:100 (A3)"), "A1")
    for page in (2, 3, 4):
        sheet = next(s for s in takeoff.sheets if s.page == page)
        assert sheet.scale is not None and sheet.scale.verified, (page, sheet.scale)
        assert sheet.scale.meters_per_pt == pytest.approx(m_per_pt(50), rel=1e-3)
        assert check_scale(sheet, declared) == [], page


def test_engine_rules_follow_the_thresholds() -> None:
    """Etikett utan ledare (SPEC 6.4.3 h.2): avstånd, konfidens, tvetydighet och parallellitet styrs av
    thresholds.yaml och skickas till motorn som --rule."""
    args = VvsEngineSource(command=["vvs-takeoff"]).rule_args()
    pairs = dict(a.split("=", 1) for a in args[1::2])
    assert args[0::2] == ["--rule"] * len(pairs)
    assert pairs["semantics.proximity.LEADERLESS_MM"] == "6.0"
    assert pairs["semantics.proximity.CONFIDENCE"] == "0.8"
    assert pairs["semantics.proximity.AMBIGUITY_RATIO"] == "1.5"
