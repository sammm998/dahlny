"""Etikettläsning på ritningar, T5 (SPEC 6.4.3 c): överlappande bitar, vision plus OCR, omläsning.

1. Sidan renderas i bitar (`tiles.size_px`, `tiles.overlap_fraction`, `tiles.dpi`). Tomma bitar hoppas över.
2. Varje bit läses av två oberoende läsare: vision-modellen (T5, via AIClient) och klassisk OCR (RapidOCR).
   OCR läser biten både som den ligger och vriden ett kvarts varv, för lodrät text.
3. Läsningarna förs till sidans koordinater (PDF-punkter). Dubbletter från överlappen slås ihop.
   Säger vision att text skärs av kanten läses biten om, förstorad.
4. Vision- och OCR-läsningar av samma etikett paras ihop:
   - lika tecken för tecken → hög konfidens;
   - olika → etiketten skärs ut i 600 dpi och läses om (T5R) med båda läsningarna som alternativ.
     Väljer omläsningen en av dem med hög säkerhet blir det texten; annars flaggas etiketten (< 0,8);
   - bara en läsare såg etiketten → konfidensen tak under granskningsgränsen.
Ingen läsning rättas mot förväntade ord. Okända suffix behålls (tolkas i grammatiken, inte här).

CLI (mätning mot facit A.4):
    python -m app.drawings.labels RITNINGAR.pdf --pages 2,3,4 --out rader.json [--no-ai] [--no-ocr]
"""

from __future__ import annotations

import argparse
import json
import time
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pymupdf

from app.ai.client import AIClient, AIError
from app.ai.datatypes import ImagePart, ProviderError, ProviderNotConfigured, TextPart
from app.ai.schemas.labels import LabelReread, TileLabels
from app.config.settings import load_thresholds
from app.ingest.pdf_typed import open_pdf, png_bytes, rect

BBox = tuple[float, float, float, float]
AI_UNAVAILABLE = (ProviderNotConfigured, ProviderError, AIError)


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
                {"text": r.text, "source": r.source, "confidence": round(r.confidence, 3)}
                for r in self.readings
            ],
        }


@dataclass
class PageLabels:
    page_no: int
    labels: list[LabelResult]
    tiles_read: int
    tiles_skipped: int
    seconds: float
    ai_run_ids: list[uuid.UUID] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


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


def _vision_tile(
    ai: AIClient, page: pymupdf.Page, tile: Tile, png: bytes, project_id: uuid.UUID | None
) -> tuple[list[Reading], bool, uuid.UUID | None]:
    result = ai.structured_result(
        "T5",
        [
            TextPart(f"Ritningsbit {tile.index} av sida {tile.page_no}, {tile.dpi} dpi."),
            ImagePart(png, label=f"p{tile.page_no}_t{tile.index}_{tile.dpi}dpi"),
        ],
        TileLabels,
        project_id=project_id,
    )
    out = []
    for lab in result.value.labels:
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
            )
        )
    return out, result.value.tile_has_cut_text, result.run_id


def _grown(tile: Tile, page: pymupdf.Page, grow: float) -> Tile:
    x0, y0, x1, y1 = tile.clip
    dx, dy = (x1 - x0) * grow / 2, (y1 - y0) * grow / 2
    r = page.rect
    return Tile(tile.page_no, tile.index, (max(0.0, x0 - dx), max(0.0, y0 - dy), min(r.width, x1 + dx),
                                          min(r.height, y1 + dy)), tile.dpi)  # fmt: skip


def read_page_labels(
    page: pymupdf.Page,
    *,
    ai: AIClient | None,
    ocr: OcrReader | None,
    project_id: uuid.UUID | None = None,
) -> PageLabels:
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
    skipped = 0
    ai_ok = ai is not None
    for tile in tiles:
        arr, png = render(page, tile.clip, dpi)
        if ink_fraction(arr, th.get("tiles.ink_threshold")) < th.get("tiles.blank_ink_fraction"):
            skipped += 1
            continue
        if ocr is not None:
            for text, box, score in ocr.read(arr):
                if score >= th.get("labels.ocr_min_score") and text.strip():
                    ocr_reads.append(Reading(text.strip(), tile.to_page(box), 0.0, score, "ocr", tile.index))
        if ai_ok and ai is not None:
            try:
                got, cut, run_id = _vision_tile(ai, page, tile, png, project_id)
                if run_id:
                    run_ids.append(run_id)
                if cut:
                    big = _grown(tile, page, th.get("tiles.cut_text_grow"))
                    _arr2, png2 = render(page, big.clip, dpi)
                    got2, _cut2, run_id2 = _vision_tile(ai, page, big, png2, project_id)
                    if run_id2:
                        run_ids.append(run_id2)
                    got = got + got2
                vision.extend(got)
            except AI_UNAVAILABLE as exc:
                problems.append(f"vision avbruten: {type(exc).__name__}: {exc}")
                ai_ok = False
    dedupe = th.get("tiles.dedupe_iou")
    vision, ocr_reads = _dedupe(vision, dedupe), _dedupe(ocr_reads, dedupe)
    labels = _combine(page, vision, ocr_reads, ai if ai_ok else None, project_id, run_ids)
    elapsed = time.monotonic() - started
    return PageLabels(page.number + 1, labels, len(tiles) - skipped, skipped, elapsed, run_ids, problems)


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
) -> list[LabelResult]:
    th = load_thresholds()
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
            out.append(_reread(page, v, o, box, ai, project_id, run_ids))
            continue
        only = v or o
        assert only is not None
        conf = min(only.confidence, cap)
        flags = [f"only_{only.source}"] + (["uncertain_chars"] if only.uncertain_chars else [])
        out.append(LabelResult(only.text, only.bbox, only.rotation, conf, only.source, [only], flags))
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
) -> LabelResult:
    th = load_thresholds()
    below = min(v.confidence, o.confidence, th.get("labels.min_read_confidence") - 0.01)
    unresolved = LabelResult(v.text, box, v.rotation, below, "vision+ocr", [v, o], ["readers_disagree"])
    if ai is None:
        return unresolved
    m = th.get("tiles.reread_margin_pt")
    clip = (max(0.0, box[0] - m), max(0.0, box[1] - m), min(page.rect.width, box[2] + m),
            min(page.rect.height, box[3] + m))  # fmt: skip
    _arr, png = render(page, clip, int(th.get("tiles.reread_dpi")))
    try:
        result = ai.structured_result(
            "T5R",
            [
                TextPart(f"Första läsningen: {v.text!r}\nAndra läsningen: {o.text!r}"),
                ImagePart(png, label=f"p{page.number + 1}_reread"),
            ],
            LabelReread,
            project_id=project_id,
        )
    except AI_UNAVAILABLE:
        return unresolved
    run_ids.append(result.run_id)
    rr = result.value
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


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", default="", help="1-baserade sidnummer, t.ex. 2,3,4 (standard: alla)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args(argv)

    ai = None
    if not args.no_ai:
        from app.db.session import make_session_factory

        ai = AIClient(make_session_factory())
    ocr = None if args.no_ocr else RapidOcrReader()
    started = time.monotonic()
    out: dict[str, Any] = {}
    run_ids: list[str] = []
    with open_pdf(args.pdf.read_bytes()) as pdf:
        pages = [int(p) for p in args.pages.split(",") if p] or list(range(1, len(pdf) + 1))
        for page_no in pages:
            res = read_page_labels(pdf[page_no - 1], ai=ai, ocr=ocr)
            run_ids += [str(r) for r in res.ai_run_ids]
            # nyckel = motorns 0-baserade sidindex, samma form som eval/tools/vvs_engine_text_rows.py
            out[str(page_no - 1)] = {
                "rows": [lab.as_json() for lab in res.labels],
                "tiles_read": res.tiles_read,
                "tiles_skipped": res.tiles_skipped,
                "seconds": round(res.seconds, 1),
                "problems": res.problems,
            }
            note = f" – {res.problems[0]}" if res.problems else ""
            print(f"sida {page_no}: {len(res.labels)} etiketter, {res.tiles_read} bitar "
                  f"({res.tiles_skipped} tomma), {res.seconds:.0f} s{note}")  # fmt: skip
    cost: float | None = None
    if ai is not None and run_ids:
        from sqlalchemy import func, select

        from app.db.models import AIRun
        from app.db.session import make_session_factory

        with make_session_factory()() as session:
            total = session.scalar(
                select(func.coalesce(func.sum(AIRun.cost_estimate), 0)).where(
                    AIRun.id.in_([uuid.UUID(r) for r in run_ids])
                )
            )
        cost = float(total or 0)
        print(f"AI-kostnad (uppskattad ur ai_run): {cost:.4f} USD för {len(run_ids)} anrop")
    out["_meta"] = {"seconds": round(time.monotonic() - started, 1), "ai_run_ids": run_ids, "cost_usd": cost,
                    "ocr": None if ocr is None else ocr.name, "ai": ai is not None}  # fmt: skip
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Totalt {out['_meta']['seconds']} s. Rader: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
