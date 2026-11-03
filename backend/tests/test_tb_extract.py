"""TB-extraktion (SPEC 6.2) på en syntetisk TB: layout, segmentering, mängd, validering, barnposter, T3G och
T4.

AI-svaren är skriptade (FakeProvider). Testerna visar att allt modellen påstår prövas mot källtexten: en RSK
eller
ett citat som inte står i texten avvisas, en beteckning som inte finns i segmentet blir ingen post, och ett
antal i
en barnpost måste stå i barnpostens egen rad.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.ai.client import AIClient
from app.ai.datatypes import ProviderRequest, TextPart
from app.ai.providers.fake import FakeProvider
from app.config.settings import load_models_config
from app.ingest.pdf_typed import new_pdf, open_pdf, pdf_bytes
from app.tb.extract import extract_tb, found_in
from app.tb.layout import read_layout
from app.tb.quantity import parse_quantity
from app.tb.segment import sections, segments

ROWS: list[tuple[str, str, str, bool]] = [
    # (KOD, TEXT, MÄNGD, fetstil i TEXT)
    ("PR", "BRUNNAR M.M.", "", False),
    ("PRB.12", "Golvbrunnar av rostfritt stål", "", False),
    ("", "B901B", "1 st", True),
    ("", "Golvbrunn av fabrikat Acme typ GB 10. Storlek 200x200x150.", "", False),
    ("", "Ansl. nr.", "25", False),
    ("PUC.1", "Tvättställ", "", False),
    ("", "TS901", "2 st", True),
    ("", "Fabrikat Acme typ T 400, RSK 1234567", "", False),
    ("", "Härtill:", "", False),
    ("", "1st blandare Acme typ BL 9, art.nr 77-01", "", False),
    ("", "2 st. avstängningsventiler Acme typ AV", "", False),
    ("", "Plastvattenlås till vägg.", "", False),
    ("PSB.1", "Kulventiler", "", False),
    ("", "AV901", "Enl. ritning", True),
    ("", "Fabrikat Acme typ KV 3.", "", False),
    ("PNU.311", "Ledningar av kopparrör", "Enl ritn", False),
    ("", "Synliga ledningar i wc ska vara förkromade.", "", False),
]


def make_tb(pages: int = 3) -> bytes:
    doc = new_pdf()
    per_page = (len(ROWS) + pages - 1) // pages
    for p in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 40), "TEKNISK BESKRIVNING", fontname="hebo", fontsize=10)
        for x, word in ((60, "KOD"), (130, "TEXT"), (457, "MÄNGD"), (499, "ENHET")):
            page.insert_text((x, 125), word, fontname="helv", fontsize=8)
        page.insert_text((60, 820), f"Sida {p + 1} av {pages}", fontname="helv", fontsize=7)
        y = 160.0
        for kod, text, mangd, bold in ROWS[p * per_page : (p + 1) * per_page]:
            if kod:
                page.insert_text((62, y), kod, fontname="helv", fontsize=9)
            page.insert_text((128, y), text, fontname="hebo" if bold else "helv", fontsize=9)
            if mangd:
                page.insert_text((470, y), mangd, fontname="helv", fontsize=9)
            y += 18
    return pdf_bytes(doc)


def test_quantity_text_is_parsed_without_guessing() -> None:
    assert parse_quantity("1 st") is not None and parse_quantity("1 st").quantity == Decimal(1)  # type: ignore[union-attr]
    assert parse_quantity("2st").quantity == Decimal(2)  # type: ignore[union-attr]
    assert parse_quantity("Enl. ritning").mode == "per_drawing"  # type: ignore[union-attr]
    rng = parse_quantity("1-2 st")
    assert rng is not None and (rng.mode, rng.minimum, rng.maximum) == ("range", Decimal(1), Decimal(2))
    assert parse_quantity("R").mode == "regulated"  # type: ignore[union-attr]
    assert parse_quantity("25") is None  # ett tal utan enhet är ingen mängd (anslutningsmått)
    assert parse_quantity("DN XX") is None


def test_layout_removes_header_and_footer_and_splits_columns() -> None:
    with open_pdf(make_tb()) as doc:
        lines = read_layout(doc)
    texts = [ln.all_text for ln in lines]
    assert not any("TEKNISK BESKRIVNING" in t or t.startswith("Sida") for t in texts)
    b901 = next(ln for ln in lines if ln.text == "B901B")
    assert b901.bold_text and b901.mangd == "1 st" and b901.kod == ""


def test_segments_follow_designations_and_ama_codes_with_a_quantity() -> None:
    with open_pdf(make_tb()) as doc:
        segs = segments(sections(read_layout(doc)))
    got = {(s.designation, s.kind, s.quantity_text) for s in segs}
    assert ("B901B", "object", "1 st") in got  # "25" i MÄNGD-kolumnen är ingen mängd
    assert ("TS901", "object", "2 st") in got
    assert ("AV901", "object", "Enl. ritning") in got
    assert ("PNU.311", "ama_item", "Enl ritn") in got  # AMA-kod med mängd på egen rad


def test_found_in_ignores_line_breaks_and_spacing() -> None:
    assert found_in("8118-0010", "typ 8118-\n0010, med")
    assert not found_in("8118-0011", "typ 8118-\n0010, med")


def _t3(req: ProviderRequest) -> dict[str, Any]:
    text = " ".join(p.text for p in req.parts if isinstance(p, TextPart))
    items: list[dict[str, Any]] = []
    sid = {
        d: t.split("|")[0].split()[-1]
        for t in text.split("[SEGMENT ")[1:]
        for d in [t.split("beteckning ")[1].split()[0]]
    }
    if "B901B" in sid:
        items.append(
            {
                "segment_id": sid["B901B"],
                "designation": "B901B",
                "kind": "object",
                "description": "Golvbrunn Acme GB 10",
                "manufacturer": "Acme",
                "model": "GB 10",
                "article_no": None,
                "rsk": "7654321",  # påhittad RSK – står inte i texten
                "dimension": "200x200x150",
                "requirement_quotes": ["Storlek 200x200x150.", "Påhittat krav"],
                "children": [],
            }
        )
        items.append(
            {
                "segment_id": sid["B901B"],
                "designation": "B999X",
                "kind": "object",  # finns inte
                "description": "x",
                "manufacturer": None,
                "model": None,
                "article_no": None,
                "rsk": None,
                "dimension": None,
                "requirement_quotes": [],
                "children": [],
            }
        )
    if "TS901" in sid:
        items.append(
            {
                "segment_id": sid["TS901"],
                "designation": "TS901",
                "kind": "object",
                "description": "Tvättställ Acme T 400",
                "manufacturer": "Acme",
                "model": "T 400",
                "article_no": None,
                "rsk": "1234567",
                "dimension": None,
                "requirement_quotes": [],
                "children": [
                    {
                        "description": "Blandare Acme BL 9",
                        "manufacturer": "Acme",
                        "model": "BL 9",
                        "article_no": "77-01",
                        "rsk": None,
                        "stated_quantity": 1,
                        "quote": "1st blandare Acme typ BL 9, art.nr 77-01",
                    },
                    {
                        "description": "Avstängningsventil Acme AV",
                        "manufacturer": "Acme",
                        "model": "AV",
                        "article_no": None,
                        "rsk": None,
                        "stated_quantity": 3,  # texten säger 2
                        "quote": "2 st. avstängningsventiler Acme typ AV",
                    },
                ],
            }
        )
    if "AV901" in sid:
        items.append(
            {
                "segment_id": sid["AV901"],
                "designation": "AV901",
                "kind": "object",
                "description": "Kulventil Acme KV 3",
                "manufacturer": "Acme",
                "model": "KV 3",
                "article_no": None,
                "rsk": None,
                "dimension": None,
                "requirement_quotes": [],
                "children": [],
            }
        )
    if "PNU.311" in sid:
        items.append(
            {
                "segment_id": sid["PNU.311"],
                "designation": "PNU.311",
                "kind": "pipe",
                "description": "Kopparrör",
                "manufacturer": None,
                "model": None,
                "article_no": None,
                "rsk": None,
                "dimension": None,
                "requirement_quotes": [],
                "children": [],
            }
        )
    return {"items": items}


T3G_REPLY = {
    "rules": [
        {
            "category": "material",
            "text": "Synliga ledningar i wc förkromade",
            "quote": "Synliga ledningar i wc ska vara förkromade.",
            "applies_to": ["wc"],
        },
        {"category": "isolering", "text": "Påhittat", "quote": "Allt isoleras 100 mm", "applies_to": []},
    ]
}
T4_REPLY = {
    "missing": [
        {"name": "Plastvattenlås", "quote": "Plastvattenlås till vägg.", "reason": "nämns i Härtill"},
        {"name": "Golvränna", "quote": "Golvränna i verkstad", "reason": "står inte i texten"},
    ]
}


def _dispatch(req: ProviderRequest) -> dict[str, Any]:
    if req.schema_name == "T3Response":
        return _t3(req)
    return T3G_REPLY if req.schema_name == "T3GResponse" else T4_REPLY


@pytest.fixture
def ai(session_factory: sessionmaker[Session]) -> AIClient:
    cfg = load_models_config()
    models = {cfg.tasks[t].model for t in ("T3", "T3G", "T4")}
    fake = FakeProvider({m: [_dispatch] * 20 for m in models})
    return AIClient(session_factory, provider_factory=lambda _n: fake, use_cache=False)


def test_extraction_validates_everything_against_the_source(ai: AIClient) -> None:
    res = extract_tb(make_tb(), "tb.pdf", ai)
    by = {it.designation: it for it in res.items}
    assert "B999X" not in by  # beteckning som inte står i segmentet → ingen post
    b = by["B901B"]
    assert b.rsk is None and any(f.startswith("rejected_rsk") for f in b.flags)  # påhittad RSK avvisas
    assert b.requirements_text == "Storlek 200x200x150." and "rejected_requirement_quotes:1" in b.flags
    assert (b.quantity, b.quantity_mode) == (Decimal(1), "fixed")
    ts = by["TS901"]
    assert ts.rsk == "1234567" and ts.quantity == Decimal(2)
    blandare, ventiler = ts.children
    assert (blandare.article_no, blandare.quantity, blandare.parent_designation) == (
        "77-01",
        Decimal(1),
        "TS901",
    )
    # "3" står inte i raden: antalet avvisas och barnposten ärver huvudpostens antal
    assert ventiler.quantity == Decimal(2) and "rejected_child_quantity:3" in ventiler.flags
    assert by["AV901"].quantity_mode == "per_drawing" and by["AV901"].quantity is None
    assert by["PNU.311"].kind == "pipe"
    assert [r.quote for r in res.rules] == ["Synliga ledningar i wc ska vara förkromade."]
    assert [d.rule_id for d in res.deviations] == ["TB_MENTIONED_NOT_ITEMIZED"]  # citat utan källa avvisas
    assert "Plastvattenlås" in res.deviations[0].message and res.deviations[0].question


def test_without_ai_no_items_are_guessed() -> None:
    res = extract_tb(make_tb(), "tb.pdf", None)
    assert res.items == [] and res.flags == ["ai_disabled"] and res.segments
