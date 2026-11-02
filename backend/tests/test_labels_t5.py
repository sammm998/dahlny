"""T5 (SPEC 6.4.3 c): bitar, vision + OCR, parning, omläsning vid oenighet, flaggning.

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
from app.config.settings import load_thresholds
from app.drawings.labels import (
    BBox,
    RapidOcrReader,
    Tile,
    ink_fraction,
    make_tiles,
    normalize,
    read_page_labels,
    render,
)
from app.ingest.pdf_typed import open_pdf

T5, T5_UP, T5R = "claude-opus-5-5", "claude-fable-5-1", "claude-fable-5-1"
PAGE = (600.0, 400.0)  # liten sida: få bitar i 300 dpi
LABEL_AT: BBox = (100.0, 100.0, 160.0, 110.0)  # etikettens läge i sidkoordinater


def page_with_text() -> bytes:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    page.insert_text((LABEL_AT[0], LABEL_AT[3]), "KV01-K1-15", fontsize=9)
    page.draw_line((100, 130), (400, 130))
    return bytes(doc.tobytes())  # type: ignore[no-untyped-call]


def tile_of(req: ProviderRequest) -> str:
    return next((p.label or "") for p in req.parts if isinstance(p, ImagePart))


def vision_reply(
    text: str, conf: float = 0.95, cut: bool = False
) -> Callable[[ProviderRequest], dict[str, Any]]:
    """Ett T5-svar som placerar etiketten på dess sidläge, omräknat till bitens pixlar ur bitens etikett."""

    def reply(req: ProviderRequest) -> dict[str, Any]:
        label = tile_of(req)
        return (
            {"labels": [], "tile_has_cut_text": cut} if "_t" not in label else _place(label, text, conf, cut)
        )

    return reply


_TILES: dict[str, Tile] = {}


def _place(label: str, text: str, conf: float, cut: bool) -> dict[str, Any]:
    tile = _TILES.get(label)
    if tile is None:
        return {"labels": [], "tile_has_cut_text": False}
    k = tile.px_per_pt
    x0, y0, x1, y1 = LABEL_AT
    if not (tile.clip[0] <= x0 and x1 <= tile.clip[2] and tile.clip[1] <= y0 and y1 <= tile.clip[3]):
        return {"labels": [], "tile_has_cut_text": False}
    box = [(x0 - tile.clip[0]) * k, (y0 - tile.clip[1]) * k, (x1 - tile.clip[0]) * k, (y1 - tile.clip[1]) * k]
    return {
        "labels": [{"text": text, "bbox_px": box, "rotation_deg": 0, "underlined": False, "has_leader": False,
                    "leader_end_px": None, "confidence": conf, "uncertain_chars": []}],
        "tile_has_cut_text": cut,
    }  # fmt: skip


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


def run(page: Any, session_factory: sessionmaker[Session] | None, *, vision: Any, ocr_text: str | None,
        reread: Any = None) -> Any:  # fmt: skip
    th = load_thresholds()
    tiles = [
        t
        for t in make_tiles(page, dpi=300, size_px=1024, overlap=0.2)
        if ink_fraction(render(page, t.clip, 300)[0], th.get("tiles.ink_threshold"))
        >= th.get("tiles.blank_ink_fraction")
    ]  # samma bitar som read_page_labels läser – tomma hoppas över
    ocr = PlacedOcr(ocr_text).bind(tiles)
    ai = None
    if session_factory is not None and vision is not None:
        replies: dict[str, list[Any]] = {T5: [vision] * 50}
        if reread is not None:
            replies[T5R] = [reread] * 5
        fake = FakeProvider(replies)
        ai = AIClient(session_factory, provider_factory=lambda _n: fake)
    return read_page_labels(page, ai=ai, ocr=ocr)


def test_tiles_cover_the_page_with_overlap() -> None:
    with open_pdf(page_with_text()) as doc:
        tiles = make_tiles(doc[0], dpi=300, size_px=1024, overlap=0.2)
    side = 1024 * 72 / 300
    assert tiles[0].clip == (0.0, 0.0, side, side)
    assert max(t.clip[2] for t in tiles) == PAGE[0] and max(t.clip[3] for t in tiles) == PAGE[1]
    assert tiles[1].clip[0] == pytest.approx(side * 0.8)  # 20 % överlapp


def test_agreeing_readers_give_high_confidence(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    res = run(pdf_page, session_factory, vision=vision_reply("KV01-K1-15"), ocr_text="KV01-K1-15")
    [lab] = [lab for lab in res.labels if normalize(lab.text) == "KV01-K1-15"]
    assert lab.method == "vision+ocr" and lab.read_confidence == 0.98 and lab.flags == []
    # samma etikett i flera överlappande bitar blir en etikett
    assert sum(1 for lab in res.labels if normalize(lab.text) == "KV01-K1-15") == 1


def test_disagreement_is_reread_and_resolved(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    reread = {"text": "KV01-K1-15", "choice": "first", "confidence": 0.95, "reason": "nollan är en nolla"}
    res = run(
        pdf_page, session_factory, vision=vision_reply("KV01-K1-15"), ocr_text="KVO1-K1-15", reread=reread
    )
    [lab] = res.labels
    assert lab.text == "KV01-K1-15" and lab.method == "vision+ocr+reread" and lab.read_confidence == 0.85
    assert lab.flags == ["reread_chose_first"]


def test_unresolved_disagreement_is_flagged(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    reread = {"text": "KV01-K1-16", "choice": "neither", "confidence": 0.6, "reason": "otydligt"}
    res = run(
        pdf_page, session_factory, vision=vision_reply("KV01-K1-15"), ocr_text="KVO1-K1-15", reread=reread
    )
    [lab] = res.labels
    assert lab.read_confidence < 0.8 and "needs_review" in lab.flags and "readers_disagree" in lab.flags


def test_single_reader_is_always_reviewed(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    res = run(pdf_page, session_factory, vision=vision_reply("KV01-K1-15", conf=0.99), ocr_text=None)
    [lab] = res.labels
    assert lab.method == "vision" and lab.read_confidence == 0.75
    assert {"only_vision", "needs_review"} <= set(lab.flags)


def test_ocr_only_without_ai(pdf_page: Any) -> None:
    res = run(pdf_page, None, vision=None, ocr_text="KV01-K1-15")
    [lab] = res.labels
    assert lab.method == "ocr" and "only_ocr" in lab.flags and lab.read_confidence <= 0.75


def test_missing_provider_falls_back_to_ocr_and_says_so(
    pdf_page: Any, session_factory: sessionmaker[Session]
) -> None:
    res = run(pdf_page, session_factory, vision=ProviderNotConfigured("ingen nyckel"), ocr_text="KV01-K1-15")
    assert res.problems and "ProviderNotConfigured" in res.problems[0]
    assert [lab.method for lab in res.labels] == ["ocr"]


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


def test_text_parts_are_sent_with_each_tile(pdf_page: Any, session_factory: sessionmaker[Session]) -> None:
    seen: list[ProviderRequest] = []

    def reply(req: ProviderRequest) -> dict[str, Any]:
        seen.append(req)
        return {"labels": [], "tile_has_cut_text": False}

    run(pdf_page, session_factory, vision=reply, ocr_text=None)
    assert seen and all(any(isinstance(p, TextPart) for p in r.parts) for r in seen)
