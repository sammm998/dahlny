"""Regelmotorn (SPEC 6.5): varje regel har minst ett positivt och ett negativt fall (SPEC 11.3)."""

from __future__ import annotations

from decimal import Decimal

from app.drawings.checks import Finding
from app.rules.catalog import SEVERITY, DeviationDraft
from app.rules.engine import RULES, AccessoryCheck, RuleContext, run_rules, sentences
from app.tb.extract import ItemDraft, TBResult
from app.tb.layout import TBLine
from app.tb.segment import sections, segments


def _lines(rows: list[tuple[str, str, str, bool]]) -> list[TBLine]:
    return [
        TBLine(
            page=1,
            y=100 + 12 * i,
            kod=k,
            text=t,
            mangd=m,
            bbox=(60, 100 + 12 * i, 500, 110 + 12 * i),
            bold_text=b,
            italic_text=False,
            spans=[],
        )
        for i, (k, t, m, b) in enumerate(rows)
    ]


def tb(rows: list[tuple[str, str, str, bool]], items: list[ItemDraft] | None = None) -> TBResult:
    lines = _lines(rows)
    for ln in lines:  # fetstil på första spannet krävs för beteckningar
        from app.tb.layout import Span

        ln.spans = [Span(128, ln.y, 200, ln.y + 8, ln.text, ln.bold_text, False)] if ln.text else []
    return TBResult(items or [], [], [], segments(sections(lines)), [], lines)


def ids(devs: list[DeviationDraft]) -> list[str]:
    return [d.rule_id for d in devs]


def item(designation: str, kind: str = "object", qty: int | None = 1) -> ItemDraft:
    return ItemDraft(
        designation,
        None,
        kind,
        None,
        None,
        designation,
        None,
        None,
        None,
        None,
        None,
        Decimal(qty) if qty is not None else None,
        None,
        None,
        "st" if qty else None,
        "fixed" if qty is not None else "per_drawing",
        None,
        [{"page": 1}],
    )


def test_every_catalog_rule_is_registered() -> None:
    assert set(RULES) == set(SEVERITY)


def test_self_contradiction_same_label_two_dimensions() -> None:
    bad = tb(
        [
            ("PRB.12", "Golvbrunnar", "", False),
            ("", "B101B", "1 st", True),
            ("", "Golvbrunn. Storlek 300x300x192. Rostfri.", "", False),
            ("", "Storlek", "", False),
            ("", "300 x 300 x 400mm", "", False),
        ]
    )
    good = tb(
        [
            ("PRB.12", "Golvbrunnar", "", False),
            ("", "B101B", "1 st", True),
            ("", "Golvbrunn. Storlek 300x300x192.", "", False),
            ("", "Storlek 300 x 300 x 192 mm", "", False),
        ]
    )
    assert ids(run_rules(RuleContext(tb=bad), ["TB_SELF_CONTRADICTION"])) == ["TB_SELF_CONTRADICTION"]
    assert run_rules(RuleContext(tb=good), ["TB_SELF_CONTRADICTION"]) == []


def test_self_contradiction_incomplete_sentence_is_info() -> None:
    bad = tb(
        [
            ("PRB.12", "Golvbrunnar", "", False),
            ("", "B102B", "1 st", True),
            ("", "Golvbrunn typ 142. Storlek  Golvtyp epoxi.", "", False),
        ]
    )
    [d] = run_rules(RuleContext(tb=bad), ["TB_SELF_CONTRADICTION"])
    assert d.effective_severity == "info" and "Storlek" in d.message
    ok = tb(
        [
            ("PRB.12", "Golvbrunnar", "", False),
            ("", "B102B", "1 st", True),
            ("", "Golvbrunn typ 142. Golvtyp epoxi.", "", False),
        ]
    )
    assert run_rules(RuleContext(tb=ok), ["TB_SELF_CONTRADICTION"]) == []


def test_option_required_merges_the_same_sentence_in_two_items() -> None:
    t = tb(
        [
            ("PRB.12", "Golvbrunnar", "", False),
            ("", "B101B", "1 st", True),
            ("", "Brunn. Radontätning ska ingå i anbudet, utredningen sker i senare skede.", "", False),
            ("", "B102B", "1 st", True),
            ("", "Brunn. Radontätning ska ingå i anbudet, utredningen sker i senare skede.", "", False),
        ]
    )
    [d] = run_rules(RuleContext(tb=t), ["OPTION_REQUIRED"])
    assert d.message.startswith("B101B/B102B")
    none = tb(
        [
            ("PRB.12", "Golvbrunnar", "", False),
            ("", "B101B", "1 st", True),
            ("", "Brunn med lock.", "", False),
        ]
    )
    assert run_rules(RuleContext(tb=none), ["OPTION_REQUIRED"]) == []


def test_decide_with_client_only_for_product_choices() -> None:
    t = tb(
        [
            ("PVH.1", "Uttag", "", False),
            ("", "Typ av snabbkoppling i samråd med beställaren.", "", False),
            ("", "Märkningen utförs i samråd med beställaren.", "", False),
        ]
    )
    [d] = run_rules(RuleContext(tb=t), ["DECIDE_WITH_CLIENT"])
    assert "snabbkoppling" in d.message


def test_undefined_value_placeholder_and_range() -> None:
    t = tb([("UGE", "Mätare", "", False), ("", "VM101", "1-2 st", True), ("", "Storlek DN XX", "", False)])
    [d] = run_rules(RuleContext(tb=t), ["UNDEFINED_VALUE"])
    assert "DN XX" in d.message and "1-2 st" in d.message
    ok = tb([("UGE", "Mätare", "", False), ("", "VM101", "1 st", True), ("", "Storlek DN25", "", False)])
    assert run_rules(RuleContext(tb=ok), ["UNDEFINED_VALUE"]) == []


def test_pass_through_rules_keep_their_source() -> None:
    t4 = DeviationDraft("TB_MENTIONED_NOT_ITEMIZED", "golvränna", [{"page": 3}])
    conflict = DeviationDraft("CONFLICTING_REQUIREMENTS", "konsoler", [{"page": 4}])
    res = TBResult([], [], [t4, conflict], [], [], [])
    assert ids(run_rules(RuleContext(tb=res), ["TB_MENTIONED_NOT_ITEMIZED"])) == ["TB_MENTIONED_NOT_ITEMIZED"]
    assert ids(run_rules(RuleContext(tb=res), ["CONFLICTING_REQUIREMENTS"])) == ["CONFLICTING_REQUIREMENTS"]
    assert run_rules(RuleContext(), ["TB_MENTIONED_NOT_ITEMIZED", "CONFLICTING_REQUIREMENTS"]) == []
    p1 = [DeviationDraft("TITLEBLOCK_MISMATCH", "x"), DeviationDraft("DRAWING_LIST_MISMATCH", "y")]
    assert ids(run_rules(RuleContext(phase1=p1), ["TITLEBLOCK_MISMATCH"])) == ["TITLEBLOCK_MISMATCH"]
    assert ids(run_rules(RuleContext(phase1=p1), ["DRAWING_LIST_MISMATCH"])) == ["DRAWING_LIST_MISMATCH"]


def test_drawing_findings_become_deviations() -> None:
    f = [
        Finding("SCALE_DISAGREEMENT", "critical", 2, "skala"),
        Finding("UNASSIGNED_PIPE", "critical", 2, "7 %"),
        Finding("UNKNOWN_LABEL_TOKEN", "warning", 2, "W40"),
    ]
    for rid in ("SCALE_DISAGREEMENT", "UNASSIGNED_PIPE", "UNKNOWN_LABEL_TOKEN"):
        assert ids(run_rules(RuleContext(drawing_findings=f), [rid])) == [rid]
        assert run_rules(RuleContext(), [rid]) == []


def test_material_code_mismatch_and_unresolved() -> None:
    res = TBResult([item("KV01-E9", "pipe", None)], [], [], [], [], [])
    assert ids(
        run_rules(RuleContext(tb=res, drawing_pipe_labels=["KV01-E13-40"]), ["MATERIAL_CODE_MISMATCH"])
    ) == ["MATERIAL_CODE_MISMATCH"]
    assert (
        run_rules(RuleContext(tb=res, drawing_pipe_labels=["KV01-E9-40"]), ["MATERIAL_CODE_MISMATCH"]) == []
    )
    flags = [("L9-22", "MATERIAL_UNRESOLVED"), ("KV01-K1-15", "MATERIAL_FROM_SYSTEM")]
    assert ids(run_rules(RuleContext(quantity_flags=flags), ["MATERIAL_UNRESOLVED"])) == [
        "MATERIAL_UNRESOLVED"
    ]


def test_quantity_vs_drawing_and_items_not_in_tb() -> None:
    res = TBResult([item("RA101", qty=2), item("B101P", qty=2)], [], [], [], [], [])
    ctx = RuleContext(tb=res, drawing_tags={"RA101": 1, "B101P": 2, "B301B": 1})
    [d] = run_rules(ctx, ["TB_QTY_VS_DRAWING"])
    assert "RA101" in d.message
    [d] = run_rules(ctx, ["DRAWING_ITEM_NOT_IN_TB"])
    assert "B301B" in d.message
    assert run_rules(RuleContext(tb=res), ["TB_QTY_VS_DRAWING", "DRAWING_ITEM_NOT_IN_TB"]) == []


def test_accessory_not_confirmed() -> None:
    acc = [AccessoryCheck("B202B", "142B1106", ["rutgaller M125"]), AccessoryCheck("B201B", "152A", [])]
    assert ids(run_rules(RuleContext(accessories=acc), ["ACCESSORY_NOT_CONFIRMED"])) == [
        "ACCESSORY_NOT_CONFIRMED"
    ]


def test_sentences_point_at_their_own_line() -> None:
    t = tb(
        [
            ("PRB.12", "Golvbrunnar", "", False),
            ("", "B101B", "1 st", True),
            ("", "Lock. Radon ingår.", "", False),
            ("", "B102B", "1 st", True),
            ("", "Lock. Radon ingår.", "", False),
        ]
    )
    radon = [s for s in sentences(t) if s.text.startswith("Radon")]
    assert [s.segment for s in radon] == ["B101B", "B102B"]
