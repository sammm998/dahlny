"""T5 (SPEC 6.4.3 c): bitar, OCR först, sortering (T5T), vision + OCR, omläsning, eskalering, bladbudget.

Vision kommer från FakeProvider och OCR från en skriptad läsare – testerna verifierar flödet och reglerna,
inte läsförmågan. Den mäts mot facit A.4 med eval/tools/label_metrics.py.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
import pymupdf
import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.ai.client import AIClient
from app.ai.datatypes import ImagePart, ProviderNotConfigured, ProviderRequest, TextPart
from app.ai.providers.fake import FakeProvider
from app.config.settings import ModelsConfig, load_models_config, load_thresholds
from app.drawings import labels as labels_module
from app.drawings.labels import (
    BBox,
    PageLabels,
    RapidOcrReader,
    Reading,
    Tile,
    ink_fraction,
    make_tiles,
    normalize,
    read_page_labels,
    render,
)
from app.ingest.pdf_typed import open_pdf

# modellerna enligt models.yaml (beslut 2026-11-02)
T5T, T5, T5R, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
PAGE = (600.0, 400.0)  # liten sida: få bitar i 300 dpi
LABEL_AT: BBox = (100.0, 100.0, 160.0, 110.0)  # etikettens läge i sidkoordinater

Reply = Callable[[ProviderRequest], dict[str, Any]]


def page_with_text() -> bytes:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    page.insert_text((LABEL_AT[0], LABEL_AT[3]), "KV01-K1-15", fontsize=9)
    page.draw_line((100, 130), (400, 130))
    return bytes(doc.tobytes())  # type: ignore[no-untyped-call]


def tile_of(req: ProviderRequest) -> str:
    return next((p.label or "") for p in req.parts if isinstance(p, ImagePart))


_TILES: dict[str, Tile] = {}


def _place(label: str, text: str | None, conf: float, cut: bool) -> dict[str, Any]:
    """Etiketten på sitt sidläge, omräknat till bitens pixlar ur bitens bildetikett."""
    tile = _TILES.get(label)
    if tile is None or text is None:
        return {"labels": [], "tile_has_cut_text": False}
    k = tile.px_per_pt
    x0, y0, x1, y1 = LABEL_AT
    if not (tile.clip[0] <= x0 and x1 <= tile.clip[2] and tile.clip[1] <= y0 and y1 <= tile.clip[3]):
        return {"labels": [], "tile_has_cut_text": False}
    box = [(x0 - tile.clip[0]) * k, (y0 - tile.clip[1]) * k, (x1 - tile.clip[0]) * k, (y1 - tile.clip[1]) * k]
    found: dict[str, Any] = {
        "text": text, "bbox_px": box, "rotation_deg": 0, "confidence": conf, "uncertain_chars": []
    }  # fmt: skip
    return {"labels": [found], "tile_has_cut_text": cut}


def vision_reply(text: str, conf: float = 0.95, cut: bool = False) -> Reply:
    """Ett T5-svar."""

    def reply(req: ProviderRequest) -> dict[str, Any]:
        return _place(tile_of(req), text, conf, cut)

    return reply


def triage_reply(kind: str, text: str | None = None) -> Reply:
    """Ett T5T-svar: sortering, och för enkla bitar även läsningen."""

    def reply(req: ProviderRequest) -> dict[str, Any]:
        labels = _place(tile_of(req), text, 0.95, False)["labels"]
        return {"kind": kind, "reason": "test", "labels": labels, "tile_has_cut_text": False}

    return reply


@pytest.fixture
def pdf_page() -> Any:
    with open_pdf(page_with_text()) as doc:
        page = doc[0]
        for t in make_tiles(page, dpi=300, size_px=1024, overlap=0.2):
            _TILES[f"p1_t{t.index}_300dpi"] = t
        yield page
    _TILES.clear()


class PlacedOcr:
    """OCR som läser `text` i varje bit där etiketten ligger helt."""

    name = "placerad"

    def __init__(self, text: str | None, score: float = 0.99) -> None:
        self.text, self.score = text, score
        self._tiles: Iterator[Tile] = iter([])  # sätts av testet

    def bind(self, tiles: list[Tile]) -> PlacedOcr:
        self._tiles = iter(tiles)
        return self

    def read(self, image: np.ndarray) -> list[tuple[str, BBox, float]]:
        tile = next(self._tiles)
        x0, y0, x1, y1 = LABEL_AT
        if self.text is None or not (tile.clip[0] <= x0 and x1 <= tile.clip[2]):
            return []
        k = tile.px_per_pt
        return [(self.text, ((x0 - tile.clip[0]) * k, (y0 - tile.clip[1]) * k, (x1 - tile.clip[0]) * k,
                             (y1 - tile.clip[1]) * k), self.score)]  # fmt: skip


def run(
    page: Any,
    session_factory: sessionmaker[Session] | None,
    *,
    ocr_text: str | None,
    triage: Any = None,
    vision: Any = None,
    reread: Any = None,
    escalated: Any = None,
    use_ocr: bool = True,
    budget_usd: float | None = None,
    routing: str = "tiles",
) -> tuple[PageLabels, FakeProvider | None]:
    th = load_thresholds()
    tiles = [
        t
        for t in make_tiles(page, dpi=300, size_px=1024, overlap=0.2)
        if ink_fraction(render(page, t.clip, 300)[0], th.get("tiles.ink_threshold"))
        >= th.get("tiles.blank_ink_fraction")
    ]  # samma bitar som read_page_labels läser – tomma hoppas över
    ocr = PlacedOcr(ocr_text).bind(tiles) if use_ocr else None
    ai, fake = None, None
    if session_factory is not None:

        def sonnet(req: ProviderRequest) -> dict[str, Any]:
            # T5 och T5R körs båda av Sonnet: omläsningens bild heter p{n}_reread
            handler = reread if tile_of(req).endswith("_reread") else vision
            assert handler is not None, f"oväntat Sonnet-anrop: {tile_of(req)}"
            return dict(handler) if isinstance(handler, dict) else handler(req)

        replies: dict[str, list[Any]] = {}
        if triage is not None:
            replies[T5T] = [triage] * 50
        if vision is not None or reread is not None:
            replies[T5] = [sonnet] * 50
        if escalated is not None:  # T5R:s eskalering när Sonnet inte kan avgöra
            replies[OPUS] = [escalated] * 10
        fake = FakeProvider(replies)
        raw = load_models_config().model_dump()
        raw["labels_routing"] = routing
        config = ModelsConfig.model_validate(raw)
        ai = AIClient(session_factory, config=config, provider_factory=lambda _n: fake)
    return read_page_labels(page, ai=ai, ocr=ocr, budget_usd=budget_usd), fake


def models_called(fake: FakeProvider | None) -> list[str]:
    assert fake is not None
    return [c.model for c in fake.calls]


def test_tiles_cover_the_page_with_overlap() -> None:
    with open_pdf(page_with_text()) as doc:
        tiles = make_tiles(doc[0], dpi=300, size_px=1024, overlap=0.2)
    side = 1024 * 72 / 300
    assert tiles[0].clip == (0.0, 0.0, side, side)
    assert max(t.clip[2] for t in tiles) == PAGE[0] and max(t.clip[3] for t in tiles) == PAGE[1]
    assert tiles[1].clip[0] == pytest.approx(side * 0.8)  # 20 % överlapp


def test_hard_tile_goes_to_sonnet_and_agreement_gives_high_confidence(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("KV01-K1-15"),
        ocr_text="KV01-K1-15",
    )  # fmt: skip
    [lab] = [lab for lab in res.labels if normalize(lab.text) == "KV01-K1-15"]
    assert lab.method == "vision+ocr" and lab.read_confidence == 0.98 and lab.flags == []
    assert {r.model for r in lab.readings if r.source == "vision"} == {T5}
    # samma etikett i flera överlappande bitar blir en etikett
    assert sum(1 for lab in res.labels if normalize(lab.text) == "KV01-K1-15") == 1
    assert set(models_called(fake)) == {T5T, T5} and res.stats.t5 >= 1
    assert res.cost_usd is not None and res.cost_usd > 0  # bladets kostnad loggas


def test_simple_tile_is_read_by_haiku_without_sonnet(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("simple", "KV01-K1-15"), ocr_text="KV01-K1-15"
    )
    [lab] = res.labels
    assert lab.method == "vision+ocr" and lab.read_confidence == 0.98
    assert {r.model for r in lab.readings if r.source == "vision"} == {T5T}
    assert set(models_called(fake)) == {T5T} and res.stats.simple >= 1 and res.stats.t5 == 0


def test_hard_tile_where_haiku_and_ocr_agree_skips_sonnet(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard", "KV01-K1-15"), ocr_text="KV01-K1-15"
    )
    [lab] = res.labels
    assert lab.read_confidence == 0.98 and set(models_called(fake)) == {T5T}
    assert res.stats.verified >= 1 and res.stats.t5 == 0


def test_hard_tile_where_haiku_and_ocr_disagree_goes_to_sonnet(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res, _ = run(
        pdf_page, session_factory, triage=triage_reply("hard", "KVO1-K1-15"),
        vision=vision_reply("KV01-K1-15"), ocr_text="KV01-K1-15",
    )  # fmt: skip
    [lab] = res.labels
    assert lab.read_confidence == 0.98 and {r.model for r in lab.readings if r.source == "vision"} == {T5}
    assert res.stats.t5 >= 1 and res.stats.verified == 0


def test_label_routing_sends_only_disagreeing_labels_to_sonnet(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    reread = {"text": "KV01-K1-15", "choice": "second", "confidence": 0.95, "reason": "nolla"}
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard", "KVO1-K1-15"), reread=reread,
        ocr_text="KV01-K1-15", routing="labels",
    )  # fmt: skip
    [lab] = res.labels
    assert lab.text == "KV01-K1-15" and lab.read_confidence == 0.85 and lab.method == "vision+ocr+reread"
    assert fake is not None and all(tile_of(c).endswith("_reread") for c in fake.calls if c.model == T5)
    assert res.stats.t5 == 0 and res.stats.rereads == 1 and res.stats.hard >= 1


def test_label_routing_agreement_needs_no_sonnet(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard", "KV01-K1-15"), ocr_text="KV01-K1-15",
        routing="labels",
    )  # fmt: skip
    [lab] = res.labels
    assert lab.read_confidence == 0.98 and set(models_called(fake)) == {T5T}


def test_label_routing_confirms_a_single_reader(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    confirm = {"text": "KV01-K1-15", "choice": "first", "confidence": 0.95, "reason": "tydlig"}
    res, _ = run(
        pdf_page, session_factory, triage=triage_reply("empty"), reread=confirm, ocr_text="KV01-K1-15",
        routing="labels",
    )  # fmt: skip
    [lab] = res.labels
    assert lab.method == "ocr+reread" and lab.read_confidence == 0.85 and lab.flags == ["reread_confirmed"]


def test_label_routing_unconfirmed_single_reader_stays_flagged(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    other = {"text": "KV01-K1-16", "choice": "neither", "confidence": 0.9, "reason": "sexa"}
    res, _ = run(
        pdf_page, session_factory, triage=triage_reply("empty"), reread=other, escalated=other,
        ocr_text="KV01-K1-15", routing="labels",
    )  # fmt: skip
    [lab] = res.labels
    assert lab.read_confidence < 0.8 and "needs_review" in lab.flags and lab.text == "KV01-K1-15"


def test_cut_text_is_reread_only_without_a_whole_reading_in_a_neighbour() -> None:
    page: BBox = (0.0, 0.0, 600.0, 400.0)
    left, right = Tile(1, 0, (0.0, 0.0, 245.0, 245.0), 300), Tile(1, 1, (196.0, 0.0, 441.0, 245.0), 300)
    clips = {0: left.clip, 1: right.clip}
    cut = Reading("KV01-K", (200.0, 50.0, 244.0, 58.0), 0.0, 0.9, "vision", 0)  # vid bitens högra kant
    whole = Reading("KV01-K1-15", (200.0, 50.0, 260.0, 58.0), 0.0, 0.9, "vision", 1)
    assert labels_module._needs_regrow(left, [cut], clips, page)
    assert not labels_module._needs_regrow(left, [cut, whole], clips, page)


def test_empty_tile_by_triage_leaves_ocr_flagged(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res, fake = run(pdf_page, session_factory, triage=triage_reply("empty"), ocr_text="KV01-K1-15")
    [lab] = res.labels
    assert lab.method == "ocr" and "needs_review" in lab.flags
    assert set(models_called(fake)) == {T5T} and res.stats.empty >= 1


def test_tiles_without_ocr_text_never_go_to_ai(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("X"), ocr_text=None
    )
    assert models_called(fake) == [] and res.labels == []
    assert res.stats.no_text == res.tiles_read > 0


def test_disagreement_is_reread_and_resolved(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    reread = {"text": "KV01-K1-15", "choice": "first", "confidence": 0.95, "reason": "nollan är en nolla"}
    res, _ = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("KV01-K1-15"),
        ocr_text="KVO1-K1-15", reread=reread,
    )  # fmt: skip
    [lab] = res.labels
    assert lab.text == "KV01-K1-15" and lab.method == "vision+ocr+reread" and lab.read_confidence == 0.85
    assert lab.flags == ["reread_chose_first"]


def test_unresolved_disagreement_is_escalated_to_opus_and_stays_flagged(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    unsure = {"text": "KV01-K1-16", "choice": "neither", "confidence": 0.6, "reason": "otydligt"}
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("KV01-K1-15"),
        ocr_text="KVO1-K1-15", reread=unsure, escalated=unsure,
    )  # fmt: skip
    [lab] = res.labels
    assert lab.read_confidence < 0.8 and "needs_review" in lab.flags and "readers_disagree" in lab.flags
    assert models_called(fake).count(OPUS) == 1  # bara utsnittet, aldrig hela bitar


def test_opus_resolves_what_sonnet_could_not(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    unsure = {"text": "KV01-K1-1?", "choice": "neither", "confidence": 0.5, "reason": "otydligt"}
    sure = {"text": "KV01-K1-15", "choice": "second", "confidence": 0.95, "reason": "femman syns i 600 dpi"}
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("KV01-K1-16"),
        ocr_text="KV01-K1-15", reread=unsure, escalated=sure,
    )  # fmt: skip
    [lab] = res.labels
    assert lab.text == "KV01-K1-15" and lab.read_confidence == 0.85 and lab.flags == ["reread_chose_second"]
    assert models_called(fake).count(OPUS) == 1


def test_single_reader_is_always_reviewed(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    res, _ = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("KV01-K1-15", conf=0.99),
        ocr_text=None, use_ocr=False,
    )  # fmt: skip
    [lab] = res.labels
    assert lab.method == "vision" and lab.read_confidence == 0.75
    assert {"only_vision", "needs_review"} <= set(lab.flags)


def test_ocr_only_without_ai(pdf_page: Any) -> None:
    res, _ = run(pdf_page, None, ocr_text="KV01-K1-15")
    [lab] = res.labels
    assert lab.method == "ocr" and "only_ocr" in lab.flags and lab.read_confidence <= 0.75


def test_missing_provider_falls_back_to_ocr_and_says_so(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res, _ = run(
        pdf_page, session_factory, triage=ProviderNotConfigured("ingen nyckel"), ocr_text="KV01-K1-15"
    )
    assert res.problems and "ProviderNotConfigured" in res.problems[0]
    assert [lab.method for lab in res.labels] == ["ocr"]


def test_sheet_budget_stops_ai_and_says_so(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("KV01-K1-15"),
        ocr_text="KV01-K1-15", budget_usd=1e-9,
    )  # fmt: skip
    assert len(models_called(fake)) == 1  # första anropet går, sedan är bladets tak nått
    assert res.problems and "CostCapExceeded" in res.problems[0] and "blad 1" in res.problems[0]
    assert all(lab.read_confidence < 0.8 for lab in res.labels)  # resten bara OCR → granskning


def test_text_parts_are_sent_with_each_tile(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    _res, fake = run(
        pdf_page, session_factory, triage=triage_reply("hard"), vision=vision_reply("KV01-K1-15"),
        ocr_text="KV01-K1-15",
    )  # fmt: skip
    assert fake is not None and fake.calls
    assert all(any(isinstance(p, TextPart) for p in r.parts) for r in fake.calls)


def test_rapidocr_maps_vertical_text_back_to_the_page() -> None:
    reader = RapidOcrReader.__new__(RapidOcrReader)
    h, w = 100, 200
    image = np.zeros((h, w, 3), dtype=np.uint8)

    def fake_words(img: np.ndarray) -> list[tuple[str, np.ndarray, float]]:
        if img.shape[:2] == (h, w):
            return []
        # i den vridna bilden (w x h) ligger ordet vågrätt på rad 50–60, kolumn 10–40
        return [("AV20", np.array([[10, 50], [40, 50], [40, 60], [10, 60]], dtype=float), 0.9)]

    reader._words = fake_words  # type: ignore[method-assign,assignment]
    [(text, box, _score)] = reader.read(image)
    # tillbaka i originalet: x = y_r (50–60), y = h-1-x_r (59–89) – lodrät låda
    assert text == "AV20" and box == (50.0, 59.0, 60.0, 89.0)
