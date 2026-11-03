"""Etikettläsning på ritningar, T5 (SPEC 6.4.3 c): överlappande bitar, vision plus OCR, omläsning.

1. Sidan delas i bitar (`tiles.size_px`, `tiles.overlap_fraction`, `tiles.dpi`); bitar utan bläck hoppas över.
2. OCR (RapidOCR) läser varje bit först, som den ligger och vriden ett kvarts varv för lodrät text.
   Hittar OCR ingen text alls (ritningsram, linjer, skraffering) skickas biten inte till AI.
3. Övriga bitar sorteras och läses av T5T (Haiku): tom, enkel eller svår. En svår bit där Haiku och OCR läser
   varje etikett lika används som den är; övriga svåra läses av T5 (Sonnet). Text som skärs av bitens kant
   och inte finns hel i en grannbit (överlappet) → biten förstoras och läses om.
4. Läsningarna förs till sidans koordinater (PDF-punkter). Dubbletter från överlappen slås ihop.
5. Vision- och OCR-läsningar av samma etikett paras ihop:
   - lika tecken för tecken → hög konfidens;
   - olika → etiketten skärs ut i 600 dpi och läses om (T5R) med båda läsningarna som alternativ.
     Väljer omläsningen en av dem med hög säkerhet blir det texten; annars flaggas etiketten (< 0,8);
   - bara en läsare såg etiketten → konfidensen tak under granskningsgränsen.
6. Bitarna med flest flaggade etiketter läses av T5X (Opus), högst `tiles.escalate_max_fraction` av de
   AI-lästa bitarna. Upprepar T5X en av läsningarna tecken för tecken lyfts etiketten.
Bladets AI-kostnad har ett tak (`labels_budget_usd_per_sheet`); nås det läses resten bara med OCR (flaggat).
Ingen läsning rättas mot förväntade ord. Okända suffix behålls (tolkas i grammatiken, inte här).

CLI (mätning mot facit A.4):
    python -m app.drawings.labels RITNINGAR.pdf --pages 2,3,4 --out rader.json [--no-ai] [--no-ocr]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pymupdf

from app.ai.client import AIClient, AIError, AITaskFailed, CostCapExceeded
from app.ai.datatypes import ContentPart, ImagePart, ProviderError, ProviderNotConfigured, TextPart
from app.ai.schemas.labels import LabelReread, TileLabel, TileLabels, TileTriage
from app.config.settings import load_thresholds
from app.ingest.pdf_typed import open_pdf, png_bytes, rect

BBox = tuple[float, float, float, float]
AI_UNAVAILABLE = (ProviderNotConfigured, ProviderError, AIError)
# stoppar bladets AI-läsning; AITaskFailed gäller bara den bit eller etikett som misslyckades
STOP_AI = (ProviderNotConfigured, ProviderError, CostCapExceeded)
log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- datatyper


@dataclass(frozen=True)
class Tile:
    page_no: int
    index: int
    clip: BBox  # PDF-punkter
    dpi: int

    @property
    def px_per_pt(self) -> float:
        return self.dpi / 72.0

    def to_page(self, box_px: Sequence[float]) -> BBox:
        k = self.px_per_pt
        x0, y0, x1, y1 = box_px
        return (self.clip[0] + x0 / k, self.clip[1] + y0 / k, self.clip[0] + x1 / k, self.clip[1] + y1 / k)


@dataclass(frozen=True)
class Reading:
    text: str
    bbox: BBox  # sidkoordinater
    rotation: float
    confidence: float
    source: str  # vision | ocr
    tile: int
    uncertain_chars: tuple[str, ...] = ()
    model: str | None = None  # modellen som läste (vision); None för OCR


@dataclass
class LabelResult:
    text: str
    bbox: BBox
    rotation: float
    read_confidence: float
    method: str  # vision+ocr | vision+ocr+reread | vision | ocr
    readings: list[Reading]
    flags: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": [round(v, 1) for v in self.bbox],
            "rotation": self.rotation,
            "read_confidence": round(self.read_confidence, 3),
            "method": self.method,
            "flags": self.flags,
            "readings": [
                {"text": r.text, "source": r.source, "model": r.model, "confidence": round(r.confidence, 3)}
                for r in self.readings
            ],
        }


@dataclass
class TileStats:
    """Vart bladets bitar tog vägen (bitar utan bläck räknas i PageLabels.tiles_skipped)."""

    no_text: int = 0  # OCR fann ingen text → ingen AI
    empty: int = 0  # T5T: tom
    simple: int = 0  # T5T: enkel
    hard: int = 0  # T5T: svår
    verified: int = 0  # (tiles) svår, men Haiku och OCR överens om varje etikett → ingen T5
    t5: int = 0  # bitar lästa av T5 (Sonnet)
    regrown: int = 0  # avskuren text utan hel läsning i grannbiten → biten förstorad och läst igen
    rereads: int = 0  # etikettutsnitt lästa av T5R (Sonnet)
    escalated: int = 0  # lästa igen av T5X
    failed: int = 0  # ingen modell gav giltigt svar

    def as_json(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class PageLabels:
    page_no: int
    labels: list[LabelResult]
    tiles_read: int
    tiles_skipped: int
    seconds: float
    ai_run_ids: list[uuid.UUID] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    stats: TileStats = field(default_factory=TileStats)
    cost_usd: float | None = None  # bladets nya AI-kostnad i den här körningen (cacheträffar kostar 0)


class OcrReader(Protocol):
    name: str

    def read(self, image: np.ndarray) -> list[tuple[str, BBox, float]]:
        """Ord i bilden: (text, [x0, y0, x1, y1] i pixlar, säkerhet 0–1)."""
        ...


# --------------------------------------------------------------------------- hjälpfunktioner


def normalize(text: str) -> str:
    """Jämförelseform: Unicode NFC, versaler, blanksteg ihopslagna. Inga tecken byts (0/O förblir olika)."""
    return " ".join(unicodedata.normalize("NFC", text).upper().split())


def iou(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def overlap_of_smaller(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small > 0 else 0.0


def make_tiles(page: pymupdf.Page, *, dpi: int, size_px: int, overlap: float) -> list[Tile]:
    side = size_px * 72.0 / dpi
    step = side * (1.0 - overlap)
    w, h = page.rect.width, page.rect.height
    tiles: list[Tile] = []
    y = 0.0
    while True:
        x = 0.0
        y1 = min(y + side, h)
        while True:
            x1 = min(x + side, w)
            tiles.append(Tile(page.number + 1, len(tiles), (x, y, x1, y1), dpi))
            if x1 >= w:
                break
            x += step
        if y1 >= h:
            break
        y += step
    return tiles


def render(page: pymupdf.Page, clip: BBox, dpi: int) -> tuple[np.ndarray, bytes]:
    pix = page.get_pixmap(dpi=dpi, clip=rect(clip), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()
    return arr, png_bytes(pix)


def ink_fraction(arr: np.ndarray, threshold: float) -> float:
    gray = arr.mean(axis=2) if arr.ndim == 3 else arr
    return float((gray < threshold).mean())


# --------------------------------------------------------------------------- OCR


class RapidOcrReader:
    """RapidOCR (PaddleOCR-modeller via ONNX). Läser bilden som den ligger och vriden 90°, för lodrät text."""

    name = "rapidocr"

    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self._engine = RapidOCR()

    def _words(self, image: np.ndarray) -> list[tuple[str, np.ndarray, float]]:
        from rapidocr.utils.output import RapidOCROutput

        out = self._engine(image)
        if not isinstance(out, RapidOCROutput) or out.boxes is None or out.txts is None or out.scores is None:
            return []
        return [
            (str(t), np.asarray(b, dtype=float), float(s))
            for b, t, s in zip(out.boxes, out.txts, out.scores, strict=False)
        ]

    def read(self, image: np.ndarray) -> list[tuple[str, BBox, float]]:
        h, w = image.shape[:2]
        found: list[tuple[str, BBox, float]] = []
        for text, quad, score in self._words(image):
            found.append(
                (text, (quad[:, 0].min(), quad[:, 1].min(), quad[:, 0].max(), quad[:, 1].max()), score)
            )
        # vriden medurs ett kvarts varv: np.rot90(k=-1) flyttar pixel (x, y) till (h-1-y, x), så en punkt
        # (x_r, y_r) i den vridna bilden är (y_r, h-1-x_r) i originalet
        turned = np.ascontiguousarray(np.rot90(image, k=-1))
        for text, quad, score in self._words(turned):
            xs = quad[:, 1]
            ys = (h - 1) - quad[:, 0]
            box = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
            if box[3] - box[1] <= box[2] - box[0]:
                continue  # inte lodrät text: redan läst i första varvet
            found.append((text, box, score))
        return [(t, b, s) for t, b, s in found if 0 <= b[0] < w + 1 and 0 <= b[1] < h + 1]


# --------------------------------------------------------------------------- läsning av en sida


def _dedupe(readings: list[Reading], dedupe_iou: float) -> list[Reading]:
    """Samma läsare, samma text, överlappande lådor (från bitarnas överlapp) → en läsning, den säkraste."""
    kept: list[Reading] = []
    for r in sorted(readings, key=lambda r: (-r.confidence, r.tile)):
        dup = False
        for k in kept:
            same_text = normalize(k.text) == normalize(r.text)
            if same_text and (iou(k.bbox, r.bbox) >= dedupe_iou or overlap_of_smaller(k.bbox, r.bbox) >= 0.9):
                dup = True
                break
            # en avskuren läsning vid bitens kant är en del av en hel läsning av samma text i grannbiten
            if overlap_of_smaller(k.bbox, r.bbox) >= 0.9 and normalize(r.text) in normalize(k.text):
                dup = True
                break
        if not dup:
            kept.append(r)
    return kept


def _readings(tile: Tile, labels: Sequence[TileLabel], model: str | None) -> list[Reading]:
    out = []
    for lab in labels:
        if not lab.text.strip():
            continue
        out.append(
            Reading(
                text=lab.text.strip(),
                bbox=tile.to_page(lab.bbox_px),
                rotation=lab.rotation_deg,
                confidence=lab.confidence,
                source="vision",
                tile=tile.index,
                uncertain_chars=tuple(lab.uncertain_chars),
                model=model,
            )
        )
    return out


def _tile_parts(tile: Tile, png: bytes) -> list[ContentPart]:
    return [
        TextPart(f"Ritningsbit {tile.index} av sida {tile.page_no}, {tile.dpi} dpi."),
        ImagePart(png, label=f"p{tile.page_no}_t{tile.index}_{tile.dpi}dpi"),
    ]


def _vision_tile(
    ai: AIClient, task_id: str, tile: Tile, png: bytes, project_id: uuid.UUID | None, run_ids: list[uuid.UUID]
) -> tuple[list[Reading], bool]:
    """En bit läst av T5 eller T5X: (läsningar, skär kanten genom text?)."""
    result = ai.structured_result(task_id, _tile_parts(tile, png), TileLabels, project_id=project_id)
    run_ids.append(result.run_id)
    return _readings(
        tile, result.value.labels, result.served_model or result.model
    ), result.value.tile_has_cut_text


def _grown(tile: Tile, page: pymupdf.Page, grow: float) -> Tile:
    x0, y0, x1, y1 = tile.clip
    dx, dy = (x1 - x0) * grow / 2, (y1 - y0) * grow / 2
    r = page.rect
    return Tile(tile.page_no, tile.index, (max(0.0, x0 - dx), max(0.0, y0 - dy), min(r.width, x1 + dx),
                                          min(r.height, y1 + dy)), tile.dpi)  # fmt: skip


def _agrees_with_ocr(haiku: list[Reading], tile_ocr: list[Reading]) -> bool:
    """Varje Haiku-läsning har en OCR-läsning på samma plats med samma tecken, och tvärtom."""
    if not haiku:
        return False
    pairs = _pair(haiku, tile_ocr, load_thresholds().get("labels.pair_iou"))
    return all(
        v is not None and o is not None and normalize(v.text) == normalize(o.text) and not v.uncertain_chars
        for v, o in pairs
    )


def _read_tile(
    ai: AIClient, tile: Tile, png: bytes, tile_ocr: list[Reading], project_id: uuid.UUID | None,
    run_ids: list[uuid.UUID], stats: TileStats,
) -> tuple[list[Reading], str | None]:  # fmt: skip
    """Haiku (T5T) sorterar och läser biten. Returnerar (läsningar, uppgift som såg avskuren text eller None).

    labels_routing = labels: Haikus läsning används; etiketter där Haiku och OCR inte enas läses om som
    utsnitt (T5R). labels_routing = tiles: svår bit → T5 (Sonnet), utom när Haiku och OCR läser varje
    etikett lika. Ogiltigt svar från T5T → T5 i båda lägena."""
    try:
        tri = ai.structured_result("T5T", _tile_parts(tile, png), TileTriage, project_id=project_id)
    except AITaskFailed:
        tri = None
    if tri is not None:
        run_ids.append(tri.run_id)
        haiku = _readings(tile, tri.value.labels, tri.served_model or tri.model)
        cut = "T5T" if tri.value.tile_has_cut_text else None
        kind = tri.value.kind
        if kind == "empty":
            stats.empty += 1
            return [], None
        stats.simple += kind == "simple"
        stats.hard += kind == "hard"
        if ai.config.labels_routing == "labels":
            return haiku, cut
        if cut is None and (kind == "simple" or _agrees_with_ocr(haiku, tile_ocr)):
            stats.verified += kind == "hard"
            return haiku, None
    stats.t5 += 1
    got, t5_cut = _vision_tile(ai, "T5", tile, png, project_id, run_ids)
    return got, "T5" if t5_cut else None


def _at_inner_edge(box: BBox, clip: BBox, page: BBox, margin: float) -> bool:
    """Ligger lådan vid en kant av biten som inte är sidans kant (där text kan ha skurits av)?"""
    return (
        (box[0] - clip[0] <= margin and clip[0] > page[0])
        or (clip[2] - box[2] <= margin and clip[2] < page[2])
        or (box[1] - clip[1] <= margin and clip[1] > page[1])
        or (clip[3] - box[3] <= margin and clip[3] < page[3])
    )


def _needs_regrow(tile: Tile, vision: list[Reading], clips: dict[int, BBox], page: BBox) -> bool:
    """Avskuren text behöver läsas om bara om ingen grannbit har en hel läsning som täcker den."""
    margin = load_thresholds().get("tiles.edge_margin_pt")
    for r in vision:
        if r.tile != tile.index or not _at_inner_edge(r.bbox, tile.clip, page, margin):
            continue
        covered = any(
            k.tile != r.tile
            and overlap_of_smaller(k.bbox, r.bbox) >= 0.9
            and normalize(r.text) in normalize(k.text)
            and not _at_inner_edge(k.bbox, clips[k.tile], page, margin)
            for k in vision
        )
        if not covered:
            return True
    return False


def read_page_labels(
    page: pymupdf.Page,
    *,
    ai: AIClient | None,
    ocr: OcrReader | None,
    project_id: uuid.UUID | None = None,
    max_tiles: int | None = None,
    budget_usd: float | None = None,
) -> PageLabels:
    """max_tiles: läs bara de första N bitarna med bläck (provkörning för att uppskatta kostnad).
    budget_usd: tak för bladets AI-kostnad (standard: labels_budget_usd_per_sheet i models.yaml)."""
    if ai is None:
        return _read_page(page, None, ocr, project_id, max_tiles)
    budget = budget_usd if budget_usd is not None else ai.config.labels_budget_usd_per_sheet
    before = ai.spent_usd
    with ai.budget_scope(budget, f"blad {page.number + 1} ({budget} USD)"):
        res = _read_page(page, ai, ocr, project_id, max_tiles)
    res.cost_usd = float(ai.spent_usd - before)
    log.info("T5 sida %s: %.4f USD, %s", res.page_no, res.cost_usd, res.stats)
    return res


def _read_page(
    page: pymupdf.Page, ai: AIClient | None, ocr: OcrReader | None, project_id: uuid.UUID | None,
    max_tiles: int | None,
) -> PageLabels:  # fmt: skip
    th = load_thresholds()
    started = time.monotonic()
    dpi = int(th.get("tiles.dpi"))
    tiles = make_tiles(
        page, dpi=dpi, size_px=int(th.get("tiles.size_px")), overlap=th.get("tiles.overlap_fraction")
    )
    vision: list[Reading] = []
    ocr_reads: list[Reading] = []
    run_ids: list[uuid.UUID] = []
    problems: list[str] = []
    stats = TileStats()
    ai_tiles: list[Tile] = []
    cut_tiles: list[tuple[Tile, str]] = []
    skipped = 0
    n_read = 0
    ai_ok = ai is not None
    for tile in tiles:
        arr, png = render(page, tile.clip, dpi)
        if ink_fraction(arr, th.get("tiles.ink_threshold")) < th.get("tiles.blank_ink_fraction"):
            skipped += 1
            continue
        if max_tiles is not None and n_read >= max_tiles:
            break
        n_read += 1
        tile_ocr: list[Reading] = []
        if ocr is not None:
            found = ocr.read(arr)
            if not found:
                stats.no_text += 1
                continue  # OCR först: utan text (ram, linjer, skraffering) går biten aldrig till AI
            for text, box, score in found:
                if score >= th.get("labels.ocr_min_score") and text.strip():
                    tile_ocr.append(Reading(text.strip(), tile.to_page(box), 0.0, score, "ocr", tile.index))
            ocr_reads.extend(tile_ocr)
        if ai_ok and ai is not None:
            try:
                got, cut_by = _read_tile(ai, tile, png, tile_ocr, project_id, run_ids, stats)
                vision.extend(got)
                ai_tiles.append(tile)
                if cut_by:
                    cut_tiles.append((tile, cut_by))
            except AITaskFailed as exc:
                stats.failed += 1
                problems.append(f"bit {tile.index}: {exc}")
            except STOP_AI as exc:
                problems.append(f"vision avbruten: {type(exc).__name__}: {exc}")
                ai_ok = False
    if ai_ok and ai is not None and cut_tiles:
        ai_ok = _regrow(page, cut_tiles, tiles, vision, ai, project_id, run_ids, stats, problems)
    dedupe = th.get("tiles.dedupe_iou")
    vision, ocr_reads = _dedupe(vision, dedupe), _dedupe(ocr_reads, dedupe)
    labels = _combine(page, vision, ocr_reads, ai if ai_ok else None, project_id, run_ids, stats)
    if ai_ok and ai is not None:
        try:
            _escalate(page, labels, ai_tiles, ai, project_id, run_ids, stats)
        except STOP_AI as exc:
            problems.append(f"eskalering avbruten: {type(exc).__name__}: {exc}")
    elapsed = time.monotonic() - started
    return PageLabels(page.number + 1, labels, n_read, skipped, elapsed, run_ids, problems, stats=stats)


def _regrow(
    page: pymupdf.Page, cut_tiles: list[tuple[Tile, str]], tiles: list[Tile], vision: list[Reading],
    ai: AIClient,
    project_id: uuid.UUID | None, run_ids: list[uuid.UUID], stats: TileStats, problems: list[str],
) -> bool:  # fmt: skip
    """Förstora och läs om (med samma uppgift som läste biten) de bitar där avskuren text saknar en hel
    läsning i en grannbit. Returnerar False om AI-läsningen fick avbrytas."""
    th = load_thresholds()
    clips = {t.index: t.clip for t in tiles}
    page_box: BBox = (0.0, 0.0, page.rect.width, page.rect.height)
    todo = [(t, task) for t, task in cut_tiles if _needs_regrow(t, vision, clips, page_box)]
    for tile, task in todo:
        big = _grown(tile, page, th.get("tiles.cut_text_grow"))
        _arr, png = render(page, big.clip, tile.dpi)
        try:
            if task == "T5T":
                tri = ai.structured_result("T5T", _tile_parts(big, png), TileTriage, project_id=project_id)
                run_ids.append(tri.run_id)
                got = _readings(big, tri.value.labels, tri.served_model or tri.model)
            else:
                got, _cut = _vision_tile(ai, task, big, png, project_id, run_ids)
        except AITaskFailed as exc:
            problems.append(f"bit {tile.index} förstorad: {exc}")
            continue
        except STOP_AI as exc:
            problems.append(f"vision avbruten: {type(exc).__name__}: {exc}")
            return False
        stats.regrown += 1
        vision.extend(got)
    return True


def _center_in(box: BBox, clip: BBox) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return clip[0] <= cx <= clip[2] and clip[1] <= cy <= clip[3]


def _escalate(
    page: pymupdf.Page, labels: list[LabelResult], ai_tiles: list[Tile], ai: AIClient,
    project_id: uuid.UUID | None, run_ids: list[uuid.UUID], stats: TileStats,
) -> None:  # fmt: skip
    """Bitarna med flest flaggade etiketter läses av T5X (Opus), högst tiles.escalate_max_fraction av de
    AI-lästa bitarna. En flaggad etikett vars läsning T5X upprepar tecken för tecken lyfts: överens med OCR
    → samma regel som vision+OCR; överens bara med en annan visionmodell → som en lyckad omläsning."""
    th = load_thresholds()
    min_conf = th.get("labels.min_read_confidence")
    limit = math.floor(th.get("tiles.escalate_max_fraction") * len(ai_tiles))
    left = [lab for lab in labels if lab.read_confidence < min_conf]
    chosen: list[tuple[Tile, list[LabelResult]]] = []
    while left and len(chosen) < limit:
        tile = max(ai_tiles, key=lambda t: (sum(_center_in(lab.bbox, t.clip) for lab in left), -t.index))
        mine = [lab for lab in left if _center_in(lab.bbox, tile.clip)]
        if not mine:
            break
        chosen.append((tile, mine))
        left = [lab for lab in left if lab not in mine]
    pair_iou = th.get("labels.pair_iou")
    for tile, mine in chosen:
        _arr, png = render(page, tile.clip, tile.dpi)
        try:
            got, _cut = _vision_tile(ai, "T5X", tile, png, project_id, run_ids)
        except AITaskFailed:
            for lab in mine:
                lab.flags.append("escalation_failed")
            continue
        stats.escalated += 1
        for lab in mine:
            best = max(got, key=lambda x: iou(x.bbox, lab.bbox), default=None)
            if (
                best is None
                or max(iou(best.bbox, lab.bbox), overlap_of_smaller(best.bbox, lab.bbox)) < pair_iou
            ):
                lab.flags.append("escalated_not_seen")
                continue
            same = [r for r in lab.readings if normalize(r.text) == normalize(best.text)]
            lab.readings.append(best)
            if not same:
                lab.flags.append(f"escalated_read:{best.text!r}")
                continue
            with_ocr = any(r.source == "ocr" for r in same)
            lab.text = same[0].text
            lab.read_confidence = th.get(
                "labels.agree_confidence" if with_ocr else "labels.reread_confidence"
            )
            lab.method += "+escalated"
            lab.flags = [f"escalated_agrees_{'ocr' if with_ocr else 'vision'}"]


def _pair(
    vision: list[Reading], ocr_reads: list[Reading], pair_iou: float
) -> list[tuple[Reading | None, Reading | None]]:
    """Para ihop vision- och OCR-läsningar av samma etikett (störst överlapp först, en mot en)."""
    cand = []
    for i, v in enumerate(vision):
        for j, o in enumerate(ocr_reads):
            score = max(iou(v.bbox, o.bbox), overlap_of_smaller(v.bbox, o.bbox) * 0.99)
            if score >= pair_iou:
                cand.append((score, i, j))
    used_v: set[int] = set()
    used_o: set[int] = set()
    pairs: list[tuple[Reading | None, Reading | None]] = []
    for _score, i, j in sorted(cand, reverse=True):
        if i in used_v or j in used_o:
            continue
        used_v.add(i)
        used_o.add(j)
        pairs.append((vision[i], ocr_reads[j]))
    pairs += [(v, None) for i, v in enumerate(vision) if i not in used_v]
    pairs += [(None, o) for j, o in enumerate(ocr_reads) if j not in used_o]
    return pairs


def _union(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _combine(
    page: pymupdf.Page,
    vision: list[Reading],
    ocr_reads: list[Reading],
    ai: AIClient | None,
    project_id: uuid.UUID | None,
    run_ids: list[uuid.UUID],
    stats: TileStats | None = None,
) -> list[LabelResult]:
    th = load_thresholds()
    stats = stats if stats is not None else TileStats()
    cap = th.get("labels.single_reader_cap")
    min_conf = th.get("labels.min_read_confidence")
    out: list[LabelResult] = []
    for v, o in _pair(vision, ocr_reads, th.get("labels.pair_iou")):
        if v and o:
            box = _union(v.bbox, o.bbox)
            if normalize(v.text) == normalize(o.text):
                conf = th.get("labels.agree_confidence")
                flags = ["uncertain_chars"] if v.uncertain_chars else []
                out.append(LabelResult(v.text, box, v.rotation, conf, "vision+ocr", [v, o], flags))
                continue
            out.append(_reread(page, v, o, box, ai, project_id, run_ids, stats))
            continue
        only = v or o
        assert only is not None
        conf = min(only.confidence, cap)
        flags = [f"only_{only.source}"] + (["uncertain_chars"] if only.uncertain_chars else [])
        single = LabelResult(only.text, only.bbox, only.rotation, conf, only.source, [only], flags)
        if ai is not None and ai.config.labels_routing == "labels":
            single = _confirm(page, single, ai, project_id, run_ids, stats)
        out.append(single)
    for lab in out:
        if lab.read_confidence < min_conf and "needs_review" not in lab.flags:
            lab.flags.append("needs_review")
    return sorted(out, key=lambda r: (round(r.bbox[1]), r.bbox[0]))


def _reread(
    page: pymupdf.Page,
    v: Reading,
    o: Reading,
    box: BBox,
    ai: AIClient | None,
    project_id: uuid.UUID | None,
    run_ids: list[uuid.UUID],
    stats: TileStats,
) -> LabelResult:
    th = load_thresholds()
    below = min(v.confidence, o.confidence, th.get("labels.min_read_confidence") - 0.01)
    unresolved = LabelResult(v.text, box, v.rotation, below, "vision+ocr", [v, o], ["readers_disagree"])
    if ai is None:
        return unresolved
    rr = _ask_reread(page, box, v.text, o.text, ai, project_id, run_ids, stats)
    if rr is None:
        return unresolved
    chosen = {"first": v.text, "second": o.text}.get(rr.choice)
    if (
        chosen is not None
        and normalize(rr.text) == normalize(chosen)
        and rr.confidence >= th.get("labels.min_read_confidence")
    ):
        return LabelResult(chosen, box, v.rotation, th.get("labels.reread_confidence"), "vision+ocr+reread",
                           [v, o], [f"reread_chose_{rr.choice}"])  # fmt: skip
    unresolved.flags.append(f"reread_{rr.choice}:{rr.text!r}")
    return unresolved


def _ask_reread(
    page: pymupdf.Page, box: BBox, first: str, second: str | None, ai: AIClient, project_id: uuid.UUID | None,
    run_ids: list[uuid.UUID], stats: TileStats,
) -> LabelReread | None:  # fmt: skip
    """T5R på ett utsnitt i 600 dpi. None om AI inte är tillgänglig (etiketten förblir flaggad)."""
    th = load_thresholds()
    m = th.get("tiles.reread_margin_pt")
    clip = (max(0.0, box[0] - m), max(0.0, box[1] - m), min(page.rect.width, box[2] + m),
            min(page.rect.height, box[3] + m))  # fmt: skip
    _arr, png = render(page, clip, int(th.get("tiles.reread_dpi")))
    second_txt = repr(second) if second is not None else "(ingen)"
    try:
        result = ai.structured_result(
            "T5R",
            [
                TextPart(f"Första läsningen: {first!r}\nAndra läsningen: {second_txt}"),
                ImagePart(png, label=f"p{page.number + 1}_reread"),
            ],
            LabelReread,
            project_id=project_id,
        )
    except AI_UNAVAILABLE:
        return None
    run_ids.append(result.run_id)
    stats.rereads += 1
    return result.value


def _confirm(
    page: pymupdf.Page, lab: LabelResult, ai: AIClient, project_id: uuid.UUID | None,
    run_ids: list[uuid.UUID], stats: TileStats,
) -> LabelResult:  # fmt: skip
    """Bara en läsare såg etiketten: T5R läser utsnittet. Bekräftar den läsningen tecken för tecken med hög
    säkerhet är två läsare överens (som en lyckad omläsning); annars förblir etiketten flaggad."""
    th = load_thresholds()
    rr = _ask_reread(page, lab.bbox, lab.text, None, ai, project_id, run_ids, stats)
    if rr is None:
        return lab
    if (
        rr.choice == "first"
        and normalize(rr.text) == normalize(lab.text)
        and rr.confidence >= th.get("labels.min_read_confidence")
    ):
        return LabelResult(lab.text, lab.bbox, lab.rotation, th.get("labels.reread_confidence"),
                           f"{lab.method}+reread", lab.readings, ["reread_confirmed"])  # fmt: skip
    lab.flags.append(f"reread_{rr.choice}:{rr.text!r}")
    return lab


# --------------------------------------------------------------------------- CLI


def _sheet_cost(run_ids: Sequence[str]) -> float:
    """Bladets AI-kostnad ur ai_run. En cacheträff räknas med originalanropets kostnad, så att en omkörning
    visar vad bladet kostar att läsa (den nya kostnaden för omkörningen står i PageLabels.cost_usd)."""
    from sqlalchemy import select

    from app.db.models import AIRun
    from app.db.session import make_session_factory

    if not run_ids:
        return 0.0
    with make_session_factory()() as session:
        runs = list(session.scalars(select(AIRun).where(AIRun.id.in_([uuid.UUID(r) for r in run_ids]))))
        total = 0.0
        for run in runs:
            src = run.request_json.get("cache_hit_of") if run.status == "cached" else None
            if src:
                orig = session.get(AIRun, uuid.UUID(str(src)))
                total += float(orig.cost_estimate or 0) if orig is not None else 0.0
            else:
                total += float(run.cost_estimate or 0)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", default="", help="1-baserade sidnummer, t.ex. 2,3,4 (standard: alla)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--model", help="modell för T5 (svåra bitar) i den här körningen")
    parser.add_argument("--max-tiles", type=int, default=None, help="läs bara de första N bitarna med bläck")
    parser.add_argument("--budget", type=float, default=None, help="kostnadstak i USD för hela körningen")
    parser.add_argument("--sheet-budget", type=float, default=None, help="kostnadstak i USD per blad")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    ai = None
    if not args.no_ai:
        from app.config.settings import ModelsConfig, load_models_config
        from app.db.session import make_session_factory

        config = load_models_config()
        if args.model:
            raw = config.model_dump()
            raw["tasks"]["T5"]["model"] = args.model
            config = ModelsConfig.model_validate(raw)
        budget = args.budget if args.budget is not None else config.cost_cap_usd_per_project
        ai = AIClient(make_session_factory(), config=config, budget_usd=budget)
        sheet = args.sheet_budget if args.sheet_budget is not None else config.labels_budget_usd_per_sheet
        models = ", ".join(f"{t}: {config.task(t).model}" for t in ("T5T", "T5", "T5R", "T5X"))
        print(f"{models}; tak {sheet} USD per blad, {budget} USD totalt")
    ocr = None if args.no_ocr else RapidOcrReader()
    started = time.monotonic()
    out: dict[str, Any] = {}
    run_ids: list[str] = []
    total_cost = 0.0
    with open_pdf(args.pdf.read_bytes()) as pdf:
        pages = [int(p) for p in args.pages.split(",") if p] or list(range(1, len(pdf) + 1))
        for page_no in pages:
            res = read_page_labels(
                pdf[page_no - 1], ai=ai, ocr=ocr, max_tiles=args.max_tiles, budget_usd=args.sheet_budget
            )
            ids = [str(r) for r in res.ai_run_ids]
            run_ids += ids
            cost = _sheet_cost(ids) if ai is not None else None
            total_cost += cost or 0.0
            # nyckel = motorns 0-baserade sidindex, samma form som eval/tools/vvs_engine_text_rows.py
            out[str(page_no - 1)] = {
                "rows": [lab.as_json() for lab in res.labels],
                "tiles_read": res.tiles_read,
                "tiles_skipped": res.tiles_skipped,
                "tiles": res.stats.as_json(),
                "seconds": round(res.seconds, 1),
                "cost_usd": None if cost is None else round(cost, 4),
                "new_cost_usd": None if res.cost_usd is None else round(res.cost_usd, 4),
                "ai_run_ids": ids,
                "problems": res.problems,
            }
            note = f" – {res.problems[0]}" if res.problems else ""
            cost_txt = "" if cost is None else f", {cost:.3f} USD"
            print(
                f"sida {page_no}: {len(res.labels)} etiketter, {res.tiles_read} bitar ({res.tiles_skipped} "
                f"utan bläck), {res.stats.as_json()}, {res.seconds:.0f} s{cost_txt}{note}"
            )
    cost_all = round(total_cost, 4) if ai is not None else None
    if cost_all is not None:
        print(f"AI-kostnad (ai_run, cacheträff = originalpris): {cost_all:.4f} USD, {len(run_ids)} anrop")
    tasks = ("T5T", "T5", "T5R", "T5X")
    out["_meta"] = {
        "seconds": round(time.monotonic() - started, 1),
        "ai_run_ids": run_ids,
        "cost_usd": cost_all,
        "models": None if ai is None else {t: ai.config.task(t).model for t in tasks},
        "model": ai.config.task("T5").model if ai is not None else None,
        "ocr": None if ocr is None else ocr.name,
        "ai": ai is not None,
    }
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Totalt {out['_meta']['seconds']} s. Rader: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
