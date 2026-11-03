"""Artikelregister, matchning och Prixel-export (SPEC 6.3, 6.7, fas 4)."""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session, sessionmaker

from app.ai.client import AIClient
from app.ai.datatypes import TextPart
from app.ai.providers.fake import FakeProvider
from app.articles.match import DbArticleSource, MatchInput, MemoryArticleSource, match_item, similarity
from app.articles.register import read_register, save_register
from app.config.settings import load_models_config
from app.export.prixel import (
    ApiExporter,
    ClipboardExporter,
    ExcelExporter,
    ExportLine,
    ExportPosition,
    PrixelApiNotConfigured,
    describe,
)

CSV = """# TESTDATA
Artikelnummer;RSK;Leverantör;Lev art.nr;Benämning;Lager;Enhet;Rabattgrupp;Tillbehör;Färg
A1;1234567;Acme;GB-10;Golvbrunn Acme GB 10 rostfri;lager;st;R1;vattenlås, rutgaller M125;grå
A2;;Acme;GB-11;Golvbrunn Acme GB 11 rostfri utan galler;virtuellt;st;R1;;
A3;;Acme;T-400;Tvättställ Acme T 400;beställningsvara;st;R2;;
A4;;Bmx;KV-3;Kulventil Bmx KV 3;lager;st;R3;;
B9;12;Acme;X;Trasig rad;lager;st;;;
B8;;Acme;Y;Okänd status;kanske;st;;;
"""


def rows() -> list[Any]:
    return read_register(CSV.encode(), "reg.csv").rows


def test_import_recognises_columns_by_header_and_rejects_bad_rows() -> None:
    res = read_register(CSV.encode(), "reg.csv")
    assert [r.dahl_art_no for r in res.rows] == ["A1", "A2", "A3", "A4"]
    assert [n for n, _ in res.rejected] == [
        6,
        7,
    ]  # RSK med fel längd, okänd lagerstatus – rad räknad från rubriken (1)
    a1 = res.rows[0]
    assert (a1.rsk, a1.stock_status, a1.accessories, a1.attributes) == (
        "1234567",
        "stock",
        ["vattenlås", "rutgaller M125"],
        {"Färg": "grå"},
    )


def test_import_takes_a_column_mapping_and_excel() -> None:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Nr", "Text", "Status"])
    ws.append(["X1", "Kulventil", "Lager"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError, match="obligatoriska"):
        read_register(buf.getvalue(), "reg.xlsx")
    res = read_register(
        buf.getvalue(), "reg.xlsx", {"dahl_art_no": "Nr", "name": "Text", "stock_status": "Status"}
    )
    assert [(r.dahl_art_no, r.name, r.stock_status) for r in res.rows] == [("X1", "Kulventil", "stock")]


def test_similarity_follows_pg_trgm() -> None:
    assert similarity("Golvbrunn GB 10", "Golvbrunn GB 10") == 1.0
    assert similarity("Golvbrunn", "Tvättställ") == 0.0


def test_rsk_exact_wins_and_stock_status_gives_the_outcome() -> None:
    r = match_item(MatchInput("TS", "TS1", "Golvbrunn", rsk="1234567"), MemoryArticleSource(rows()))
    assert (r.method, r.score, r.outcome, r.article and r.article.dahl_art_no) == ("rsk", 1.0, "stock", "A1")


def test_supplier_article_number_needs_the_manufacturer() -> None:
    src = MemoryArticleSource(rows())
    r = match_item(MatchInput("B", "B1", "Golvbrunn", manufacturer="Acme", article_no="GB 11"), src)
    assert (r.method, r.outcome) == ("art_no", "virtual")  # 0,98 ≥ 0,95 och virtuellt lager
    r = match_item(MatchInput("B", "B1", "Golvbrunn", manufacturer="Annan", article_no="GB-11"), src)
    assert r.method != "art_no"


def test_order_article_goes_to_request() -> None:
    r = match_item(
        MatchInput("T", "TS2", "Tvättställ", manufacturer="Acme", article_no="T-400"),
        MemoryArticleSource(rows()),
    )
    assert r.outcome == "request"


def test_required_accessories_must_be_confirmed() -> None:
    src = MemoryArticleSource(rows())
    item = MatchInput(
        "B1",
        "B1",
        "Golvbrunn",
        rsk="1234567",
        requirements_text="Levereras med vattenlås. Levereras med rutgaller M125. Försedd med skyddslock.",
    )
    r = match_item(item, src)
    assert r.outcome == "request" and r.accessory is not None and r.accessory.missing == ["skyddslock"]
    # ett tillbehör som bara nämns (t.ex. en egen Härtill-post) krävs inte av artikeln
    loose = MatchInput(
        "B1", "B1", "Golvbrunn", rsk="1234567", requirements_text="Skyddslock beställs separat."
    )
    assert match_item(loose, src).outcome == "stock"


def _ai(session_factory: sessionmaker[Session], reply: dict[str, Any]) -> tuple[AIClient, FakeProvider]:
    fake = FakeProvider({load_models_config().tasks["T6"].model: [reply]})
    return AIClient(session_factory, provider_factory=lambda _n: fake, use_cache=False), fake


def test_rerank_may_only_choose_among_the_candidates(session_factory: sessionmaker[Session]) -> None:
    src = MemoryArticleSource(rows())
    item = MatchInput("AV", "AV1", "Kulventil Bmx KV 3", manufacturer="Bmx", model="KV 3")
    ai, fake = _ai(session_factory, {"candidate": 0, "score": 0.97, "reason": "fabrikat och typ stämmer"})
    r = match_item(item, src, ai)
    assert (r.method, r.outcome, r.article and r.article.dahl_art_no) == ("ai", "stock", "A4")
    assert "Kulventil Bmx KV 3" in " ".join(p.text for p in fake.calls[0].parts if isinstance(p, TextPart))
    ai, _ = _ai(session_factory, {"candidate": 99, "score": 0.99, "reason": "påhittad"})
    assert match_item(item, src, ai).article is None  # index utanför listan avvisas
    ai, _ = _ai(session_factory, {"candidate": 0, "score": 0.8, "reason": "oklar storlek"})
    assert match_item(item, src, ai).outcome == "uncertain"


def test_db_source_uses_pg_trgm(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as s:
        new, upd = save_register(s, rows())
        assert (new, upd) == (4, 0) and save_register(s, rows()) == (0, 4)  # nattlig synk: upsert
        src = DbArticleSource(s)
        assert [a.dahl_art_no for a in src.by_rsk("1234567")] == ["A1"]
        assert [a.dahl_art_no for a in src.by_art_no("GB11")] == ["A2"]
        assert src.fuzzy("Kulventil Bmx KV 3", 2)[0].article.dahl_art_no == "A4"
        s.rollback()


def _positions() -> list[ExportPosition]:
    line = ExportLine(
        "142B1106",
        "Golvbrunn FURO 142",
        Decimal(1),
        "st",
        "DF9999",
        "Furhoffs",
        "stock",
        describe("273x273x250 mm", "Bottenutlopp. Utloppsdimension 110mm. Stålkvalitet EN1.4404."),
    )
    return [ExportPosition("B202B", [line])]


def test_clipboard_export_groups_rows_under_the_position() -> None:
    text = ClipboardExporter().export(_positions()).decode()
    lines = text.split("\n")
    assert lines[0] == "B202B"
    assert lines[1].split("\t")[:6] == ["1", "142B1106", "Golvbrunn FURO 142", "", "STK.", "1"]
    assert lines[1].endswith("Furhoffs") and "DF9999" in lines[1]
    assert lines[2] == "\tDim. 273x273x250 mm." and "Utloppsdimension 110mm." in text


def test_excel_export_has_header_and_bold_position_rows() -> None:
    wb = load_workbook(io.BytesIO(ExcelExporter().export(_positions())))
    ws = wb.active
    assert ws is not None
    assert ws.cell(1, 1).value == "Pos" and ws.cell(2, 1).value == "B202B" and ws.cell(2, 1).font.bold
    assert ws.cell(3, 2).value == "142B1106"


def test_api_exporter_is_a_stub_with_a_clear_message() -> None:
    with pytest.raises(PrixelApiNotConfigured, match="SPEC 14"):
        ApiExporter().export(_positions())
