"""Leverantörsförfrågningar (SPEC 6.6): gruppering, frågor, kontroll av T9:s text, .eml, Excelbilaga, T10."""

from __future__ import annotations

import email
import io
from decimal import Decimal
from email import policy
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy.orm import Session, sessionmaker

from app.ai.client import AIClient
from app.ai.providers.fake import FakeProvider
from app.articles.match import MatchInput, MatchResult
from app.articles.register import ArticleRow
from app.config.settings import load_models_config
from app.requests.mailbox import GmailDraftCreator, GraphDraftCreator, MailboxNotConfigured
from app.requests.replies import extract_prices
from app.requests.supplier import UNKNOWN_SUPPLIER, build_requests, check_body, compose, to_eml
from app.rules.catalog import DeviationDraft
from app.tb.extract import ItemDraft
from app.tb.header import ProjectInfo

PROJECT = ProjectInfo("NYBYGGNAD TESTHALL", "Testbolaget AB", "70000001")


def item(designation: str, manufacturer: str, req: str, qty: int = 1) -> ItemDraft:
    return ItemDraft(
        designation,
        None,
        "object",
        "PRB.12",
        None,
        f"Golvbrunn {manufacturer}",
        manufacturer,
        None,
        None,
        None,
        None,
        Decimal(qty),
        None,
        None,
        "st",
        "fixed",
        req,
        [{"page": 1}],
    )


def result(it: ItemDraft, outcome: str, supplier: str | None) -> MatchResult:
    art = (
        ArticleRow("D1", "Golvbrunn", "order", supplier=supplier, supplier_art_no="GB-1")
        if supplier
        else None
    )
    return MatchResult(
        MatchInput(it.designation or "", it.designation, it.description), art, "ai", 0.9, outcome, ""
    )


def drafts() -> list[Any]:
    a, b, c = (
        item("B901B", "Acme", "Levereras med rutgaller M125."),
        item("B902B", "Acme", "Storlek 200x200."),
        item("TS901", "Bmx", "Rostfri."),
    )
    res = [result(a, "request", "Acme"), result(b, "request", None), result(c, "stock", "Bmx")]
    devs = [
        DeviationDraft(
            "ACCESSORY_NOT_CONFIRMED",
            "B901B mot artikel Acme GB-1: rutgaller M125 bekräftas inte.",
            question="Ingår rutgaller M125 i Acme GB-1 (B901B)?",
        ),
        DeviationDraft(
            "OPTION_REQUIRED", 'B901B/B902B: "Radontätning ska ingå i anbudet" – prissätt som option.'
        ),
        DeviationDraft(
            "TB_SELF_CONTRADICTION", "TS901: mått olika", question="Vilket mått gäller för TS901?"
        ),
    ]
    return build_requests([a, b, c], res, devs, PROJECT)


def test_request_lines_are_grouped_by_supplier_with_their_questions_and_options() -> None:
    [acme] = drafts()  # B902B har ingen leverantör i registret: postens fabrikat (Acme) används
    assert acme.supplier == "Acme" and [ln.designation for ln in acme.lines] == ["B901B", "B902B"]
    assert acme.questions == ["Ingår rutgaller M125 i Acme GB-1 (B901B)?"]  # TS901 är lagervara, ingen fråga
    assert len(acme.options) == 1 and acme.subject == "Prisförfrågan NYBYGGNAD TESTHALL, uppdrag 70000001"


def test_unknown_supplier_is_said_as_such() -> None:
    it = item("B903B", "", "")
    it.manufacturer = None
    [d] = build_requests([it], [result(it, "request", None)], [], PROJECT)
    assert d.supplier == UNKNOWN_SUPPLIER


def test_t9_text_with_an_invented_number_is_replaced_by_the_template(
    session_factory: sessionmaker[Session],
) -> None:
    [d] = drafts()
    model = load_models_config().tasks["T9"].model
    bad = {"body_md": "Hej! Vi behöver 12 st B901B och B902B. Levereras med rutgaller M125. Storlek 200x200."}
    fake = FakeProvider({model: [bad]})
    compose(d, AIClient(session_factory, provider_factory=lambda _n: fake, use_cache=False))
    assert any(f.startswith("t9_rejected") for f in d.flags) and "tal utan källa: 12" in d.flags[0]
    assert "B901B" in d.body_md and "> Levereras med rutgaller M125." in d.body_md  # mallen, med citaten


def test_a_clean_t9_text_is_kept() -> None:
    [d] = drafts()
    body = (
        "Hej,\n\nVi ber om pris på **B901B** 1 st och **B902B** 1 st (uppdrag 70000001).\n"
        "  > Levereras med rutgaller M125.\n  > Storlek 200x200.\n"
    )
    assert check_body(d, body) == []


def test_eml_is_an_unsent_draft_with_html_and_an_excel_attachment() -> None:
    [d] = drafts()
    compose(d, None)
    msg = email.message_from_bytes(to_eml(d, "inkop@acme.example"), policy=policy.default)
    assert (
        msg["X-Unsent"] == "1"
        and msg["To"] == "inkop@acme.example"
        and msg["Subject"].startswith("Prisförfrågan")
    )
    parts = list(msg.walk())
    assert {p.get_content_type() for p in parts} >= {"text/plain", "text/html"}
    [att] = [p for p in parts if p.get_filename()]
    ws = load_workbook(io.BytesIO(att.get_content())).active
    assert ws is not None and ws.cell(2, 6).value == "Pris" and ws.cell(3, 1).value == "B901B"


def test_mailboxes_only_make_drafts_and_are_stubs_until_authorised() -> None:
    for creator in (GraphDraftCreator(), GmailDraftCreator()):
        assert not hasattr(creator, "send")
        with pytest.raises(MailboxNotConfigured, match="SPEC 14"):
            creator.create_draft(b"")


def test_reply_prices_must_be_quoted_from_the_reply(session_factory: sessionmaker[Session]) -> None:
    [d] = drafts()
    reply = "Hej! B901B GB-1: 4252,00 kr/st, leverans 2-3 veckor. B902B kan vi tyvärr inte leverera."
    lines = [
        {
            "designation": "B901B",
            "price": 4252.0,
            "currency": "SEK",
            "price_unit": "st",
            "delivery_time": "2-3 veckor",
            "replacement": None,
            "quote": "B901B GB-1: 4252,00 kr/st",
        },
        {
            "designation": "B902B",
            "price": 999.0,
            "currency": "SEK",
            "price_unit": "st",
            "delivery_time": None,
            "replacement": None,
            "quote": "B902B 999 kr",
        },
    ]
    fake = FakeProvider({load_models_config().tasks["T10"].model: [{"lines": lines}]})
    got = extract_prices(
        d, reply, AIClient(session_factory, provider_factory=lambda _n: fake, use_cache=False)
    )
    assert got[0]["price"] == 4252.0 and got[0]["flags"] == []
    assert got[1]["price"] is None and got[1]["flags"] == ["price_not_in_reply"]
