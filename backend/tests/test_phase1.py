"""Fas 1: intag, sidklassning, titelblock, ritningsförteckning (SPEC 6.1).

AI-svaren kommer från FakeProvider – testerna verifierar flödet, sammanvägningen och korskontrollerna, inte
modellens läsförmåga. Den mäts mot facit med `make eval` när en API-nyckel finns.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.client import AIClient
from app.ai.datatypes import ImagePart, ProviderNotConfigured, ProviderRequest, TextPart
from app.ai.providers.fake import FakeProvider
from app.classify.drawing_list import parse_drawing_list
from app.classify.pages import classify_page, read_title_block, rule_kind
from app.ingest.files import InputFile, UnsafeArchiveError, detect_kind, expand
from app.ingest.pdf_pages import page_features, page_format
from app.ingest.pdf_typed import open_pdf
from app.pipeline.phase1 import analyze_files, persist
from tests import pdf_factory

T1, T1_UP = "claude-haiku-5-5", "claude-sonnet-5-5"
T2, T2_UP = "claude-sonnet-5-5", "claude-opus-5-5"
LIST = [("W-50-1-1000", "PLAN 1, MARKPLAN", "1:50"), ("W-50-8-1000", "FLÖDESSCHEMA VS", "-")]


def label_of(req: ProviderRequest) -> str:
    return next((p.label or "") for p in req.parts if isinstance(p, ImagePart))


def title_block(no: str | None, *, project: str = "70230105", scale: str = "1:50 (A1) 1:100 (A3)",
                confidence: float = 0.97, uncertain: list[str] | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "found": True,
        "drawing_no": no,
        "title_lines": ["HUS 1", "PLAN 1"],
        "level_name": "PLAN 1",
        "scale_text": scale,
        "project_no": project,
        "date": "2025-09-15",
        "revision": None,
        "consultant": "Bengt Dahlgren Karlstad AB",
        "confidence": confidence,
        "uncertain_fields": uncertain or [],
    }


def scripted(kinds: dict[str, str], blocks: dict[str, dict[str, Any]]) -> Callable[[ProviderRequest], Any]:
    def reply(req: ProviderRequest) -> dict[str, Any]:
        label = label_of(req)
        page = label.split("_")[0]
        if label.endswith("_overview"):
            text = " ".join(p.text for p in req.parts if isinstance(p, TextPart))
            if "TEKNISK BESKRIVNING" in text or "INNEHÅLLSFÖRTECKNING" in text:
                return {"kind": "tb", "confidence": 0.95, "reason": "AMA-text"}
            return {"kind": kinds.get(page, "other"), "confidence": 0.95, "reason": "test"}
        return blocks.get(page, {**title_block(None), "found": False})

    return reply


def client(session_factory: sessionmaker[Session], fake: FakeProvider) -> AIClient:
    return AIClient(session_factory, provider_factory=lambda _n: fake)


# --------------------------------------------------------------------------- intag


def test_detect_kind_by_content_not_extension() -> None:
    assert detect_kind(b"%PDF-1.7 ...", "ritning.png") == "pdf"
    assert detect_kind(b"\x89PNG\r\n\x1a\n...") == "image"
    assert detect_kind(b"AC1032....") == "dwg"
    assert detect_kind(b"ISO-10303-21;\nHEADER;") == "ifc"
    assert detect_kind(b"  0\nSECTION\n  2\nHEADER") == "dxf"
    assert detect_kind(b"hello") == "unknown"


def test_zip_is_expanded_and_unsafe_paths_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("handlingar/tb.pdf", pdf_factory.tb_document(1))
        zf.writestr("__MACOSX/._tb.pdf", b"junk")
    files = list(expand("underlag.zip", buf.getvalue()))
    assert [(f.filename, f.kind) for f in files] == [("underlag.zip/handlingar/tb.pdf", "pdf")]

    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../etc/passwd", b"x")
    with pytest.raises(UnsafeArchiveError):
        list(expand("evil.zip", evil.getvalue()))


def test_page_format_and_paper_size() -> None:
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        first, drawing = page_features(doc[0]), page_features(doc[1])
    assert (first.paper_size, page_format(first)) == ("A4", "pdf_vector")
    assert (drawing.paper_size, page_format(drawing)) == ("A1", "pdf_vector")
    with open_pdf(pdf_factory.raster_page()) as doc:
        scan = page_features(doc[0])
    assert page_format(scan) == "pdf_raster" and scan.image_coverage > 0.9


# --------------------------------------------------------------------------- regler och förteckning


def test_rules_do_not_mistake_a_tb_mentioning_the_drawing_list() -> None:
    with open_pdf(pdf_factory.tb_document(3)) as doc:
        kinds = [rule_kind(p.get_text()) for p in doc]
    assert kinds == ["tb", None, "tb"]  # innehållsförteckningen saknar markörer; sida 3 nämner förteckningen


def test_drawing_list_parsed_and_footer_ignored() -> None:
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=0)) as doc:
        result = parse_drawing_list(doc[0])
    assert result.project_no == "70250105" and result.problems == []
    assert [(e.drawing_no, e.title, e.scale_text, e.no_scale) for e in result.drawings] == [
        ("W-50-1-1000", "PLAN 1, MARKPLAN", "1:50", False),
        ("W-50-8-1000", "FLÖDESSCHEMA VS", "-", True),
    ]
    assert len(result.entries) == 2  # sidfoten med adressen är ingen rad


# --------------------------------------------------------------------------- klassning och titelblock


def test_rule_and_ai_agree(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({T1: [{"kind": "tb", "confidence": 0.9, "reason": "AMA-koder"}]})
    with open_pdf(pdf_factory.tb_document(1)) as doc:
        decision = classify_page(doc[0], page_features(doc[0]), client(session_factory, fake))
    assert (decision.kind, decision.confidence, decision.needs_review) == ("tb", 0.98, False)


def test_rule_and_ai_disagree_goes_to_review(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({T1: [{"kind": "plan", "confidence": 0.9, "reason": "ser ut som en plan"}]})
    with open_pdf(pdf_factory.tb_document(1)) as doc:
        decision = classify_page(doc[0], page_features(doc[0]), client(session_factory, fake))
    assert decision.kind is None and decision.needs_review
    assert "Regeln säger tb, T1 säger plan" in decision.reasons[0]


def test_low_ai_confidence_escalates_then_flags(session_factory: sessionmaker[Session]) -> None:
    unsure = {"kind": "plan", "confidence": 0.5, "reason": "osäker"}
    fake = FakeProvider({T1: [unsure], T1_UP: [{**unsure, "confidence": 0.6}]})
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        decision = classify_page(doc[1], page_features(doc[1]), client(session_factory, fake))
    assert decision.kind == "plan" and decision.needs_review and len(fake.calls) == 2


def test_without_ai_drawing_pages_are_unclassified() -> None:
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        decision = classify_page(doc[1], page_features(doc[1]), None)
    assert decision.kind is None and decision.needs_review


def test_title_block_from_vision_is_validated(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({T2: [title_block("W-50-1-1000")]})
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        tb = read_title_block(doc[1], page_features(doc[1]), client(session_factory, fake))
    assert tb.drawing_no == "W-50-1-1000" and tb.project_no == "70230105"
    assert [s.text for s in tb.scales] == [
        "1:50 (A1)",
        "1:100 (A3)",
    ]  # tolkat med våra mönster, inte modellens
    assert tb.method == "vision" and not tb.needs_review


def test_a_demolition_drawing_is_flagged_by_its_stamp(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({T2: [title_block("W-50-1-1000"), title_block("W-50-1-1000")]})
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        plain = read_title_block(doc[1], page_features(doc[1]), client(session_factory, fake))
        doc[1].insert_text((60, 60), "DEMONTERINGSRITNING", fontsize=12)
        stamped = read_title_block(doc[1], page_features(doc[1]), client(session_factory, fake))
    assert "purpose:demolition" not in plain.flags and "purpose:demolition" in stamped.flags


def test_invented_drawing_number_format_is_rejected(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({T2: [title_block("PLAN 1")]})
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        tb = read_title_block(doc[1], page_features(doc[1]), client(session_factory, fake))
    assert tb.drawing_no is None and any(f.startswith("drawing_no_not_matching_pattern") for f in tb.flags)


def test_uncertain_title_block_escalates_and_needs_review(session_factory: sessionmaker[Session]) -> None:
    unsure = title_block("W-50-1-1000", confidence=0.9, uncertain=["drawing_no"])
    fake = FakeProvider({T2: [unsure], T2_UP: [unsure]})
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        tb = read_title_block(doc[1], page_features(doc[1]), client(session_factory, fake))
    assert tb.needs_review and len(fake.calls) == 2


def test_missing_provider_is_reported_not_guessed(session_factory: sessionmaker[Session]) -> None:
    fake = FakeProvider({T2: [ProviderNotConfigured("ingen nyckel")]})
    with open_pdf(pdf_factory.drawing_set(list_rows=LIST, drawing_pages=1)) as doc:
        tb = read_title_block(doc[1], page_features(doc[1]), client(session_factory, fake))
    assert tb.drawing_no is None and "ai_unavailable:ProviderNotConfigured" in tb.flags
    assert "title_block_not_read" in tb.flags


# --------------------------------------------------------------------------- hela fas 1


def project_files() -> list[InputFile]:
    return [
        InputFile("tb.pdf", pdf_factory.tb_document(3), "pdf"),
        InputFile("ritningar.pdf", pdf_factory.drawing_set(list_rows=LIST, drawing_pages=2), "pdf"),
    ]


def run_project(session_factory: sessionmaker[Session], blocks: dict[str, dict[str, Any]]) -> Any:
    kinds = {"page1": "drawing_list", "page2": "plan", "page3": "schematic"}
    reply = scripted(kinds, blocks)
    fake = FakeProvider({T1: [reply] * 20, T2: [reply] * 20})
    return analyze_files(project_files(), client(session_factory, fake))


def test_phase1_end_to_end_with_crosschecks(session_factory: sessionmaker[Session]) -> None:
    blocks = {
        "page2": title_block("W-50-1-1000", project="70230105"),
        "page3": {**title_block("W-50-8-1000", project="70250105"), "title_lines": ["FLÖDESSCHEMA"]},
    }
    result = run_project(session_factory, blocks)
    tb_doc, drawings = result.documents
    assert tb_doc.kind == "tb" and tb_doc.project_no == "70250105"
    assert [p.kind.kind for p in drawings.pages] == ["drawing_list", "plan", "schematic"]
    assert [p.title_block.drawing_no for p in drawings.pages[1:]] == ["W-50-1-1000", "W-50-8-1000"]
    devs = {(d.rule_id, d.effective_severity, d.message) for d in result.deviations}
    assert (
        "TITLEBLOCK_MISMATCH",
        "info",
        "Ritning W-50-1-1000 anger uppdragsnummer 70230105, handlingarna i övrigt 70250105",
    ) in devs
    assert any("W-50-8-1000: förteckningen anger ingen skala" in m for _, _, m in devs)
    assert not any(r == "DRAWING_LIST_MISMATCH" for r, _, _ in devs)


def test_missing_and_extra_drawings(session_factory: sessionmaker[Session]) -> None:
    blocks = {
        "page2": title_block("W-50-1-1000", project="70250105"),
        "page3": title_block("W-50-9-9999", project="70250105"),  # inte i förteckningen
    }
    result = run_project(session_factory, blocks)
    messages = [d.message for d in result.deviations if d.rule_id == "DRAWING_LIST_MISMATCH"]
    assert messages == [
        "Ritning W-50-8-1000 (FLÖDESSCHEMA VS) finns i ritningsförteckningen men har inte tagits emot",
        "Ritning W-50-9-9999 har tagits emot men finns inte i ritningsförteckningen",
    ]


def test_duplicates_and_unsupported_files_are_reported(session_factory: sessionmaker[Session]) -> None:
    data = pdf_factory.tb_document(1)
    files = [
        InputFile("a.pdf", data, "pdf"),
        InputFile("kopia.pdf", data, "pdf"),
        InputFile("x.dwg", b"AC10", "dwg"),
    ]
    result = analyze_files(files, None)
    assert len(result.documents) == 1
    assert result.skipped == [
        "kopia.pdf: dubblett (samma innehåll som en annan fil)",
        "x.dwg: dwg hanteras i en senare fas (SPEC 6.4.1–6.4.4)",
    ]


def test_persist_writes_documents_pages_and_deviations(session_factory: sessionmaker[Session]) -> None:
    from app.db.models import Deviation, Document, Page, Project

    blocks = {"page2": title_block("W-50-1-1000"), "page3": title_block("W-50-8-1000", project="70250105")}
    result = run_project(session_factory, blocks)
    with session_factory() as s:
        project = Project(name="Årjäng")
        s.add(project)
        s.flush()
        persist(s, project.id, result)
        s.commit()
        pages = s.scalars(select(Page).order_by(Page.page_no)).all()
        plan = next(p for p in pages if p.drawing_no == "W-50-1-1000")
        assert plan.kind == "plan" and plan.scale_declared == "1:50 (A1) 1:100 (A3)"
        assert plan.paper_size_declared == "A1"  # skalan som gäller för sidans eget format
        assert plan.title_block_json is not None and plan.title_block_json["kind_decision"]["kind"] == "plan"
        docs = s.scalars(select(Document)).all()
        assert {d.kind for d in docs} == {"tb", None}
        assert s.scalars(select(Deviation.rule_id)).all().count("TITLEBLOCK_MISMATCH") >= 2
        json.dumps(plan.title_block_json)  # går att serialisera
