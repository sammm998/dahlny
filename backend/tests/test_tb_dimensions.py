from __future__ import annotations

from decimal import Decimal

import pytest

from app.tb.dimensions import find_dimensions, same_dimension


def mm(*values: int) -> tuple[Decimal, ...]:
    return tuple(Decimal(v) for v in values)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Storlek 300x300x192.", mm(300, 300, 192)),
        ("Storlek                      300 x 300 x 400mm", mm(300, 300, 400)),
        ("273x273x250", mm(273, 273, 250)),
        ("Tvättställ 570x435", mm(570, 435)),
        ("1200 X 451 mm", mm(1200, 451)),
        ("30 × 30 × 19,2 cm", (Decimal(300), Decimal(300), Decimal("192.0"))),
        ("0,3x0,3x0,4 m", (Decimal("300.0"), Decimal("300.0"), Decimal("400.0"))),
    ],
)
def test_parses_and_normalizes_to_mm(text: str, expected: tuple[Decimal, ...]) -> None:
    [dim] = find_dimensions(text)
    assert dim.values_mm == expected


def test_b201b_contradiction_is_detected_across_spellings() -> None:
    # Bilaga A.3 nr 2: samma brunn har två olika mått i TB, skrivna på olika sätt.
    in_text = find_dimensions("betonggolv. Storlek 300x300x192. Stålkvalitet av EN1.4404")[0]
    in_table = find_dimensions("Storlek                      300 x 300 x 400mm")[0]
    assert not same_dimension(in_text, in_table)
    assert in_text.normalized == "300x300x192 mm"
    assert in_table.normalized == "300x300x400 mm"


def test_same_size_written_differently_is_equal() -> None:
    a = find_dimensions("300x300x400")[0]
    b = find_dimensions("300 x 300 x 400mm")[0]
    c = find_dimensions("30 x 30 x 40 cm")[0]
    assert same_dimension(a, b) and same_dimension(b, c)


@pytest.mark.parametrize(
    "text",
    [
        "EN1.4404",  # stålkvalitet, inget mått
        "RSK 7606418",
        "DN XX",
        "1:100",
        "300 mm x 30 cm",  # blandade enheter – lämnas till granskning
        "KV01-K1-15",
    ],
)
def test_non_dimensions_are_not_parsed(text: str) -> None:
    assert find_dimensions(text) == []


def test_word_after_number_is_not_a_unit() -> None:
    [dim] = find_dimensions("300x300 med galler")
    assert dim.values_mm == mm(300, 300) and dim.raw == "300x300"
