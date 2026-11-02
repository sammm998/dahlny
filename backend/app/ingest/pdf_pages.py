"""Egenskaper per PDF-sida och formatbestämning (SPEC 6.1.2).

En PDF kan blanda sidtyper, så format bestäms per sida: vektorer, textlager och hur stor del av sidan som
täcks av inbäddade bilder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pymupdf

from app.config.settings import load_documents_config, load_thresholds
from app.ingest.pdf_typed import page_text, png_bytes, rect

PageFormat = Literal["pdf_vector", "pdf_raster", "pdf_mixed"]
MM_PER_PT = 25.4 / 72


@dataclass(frozen=True)
class PageFeatures:
    page_no: int  # 1-baserat, som i handlingarna
    width_pt: float
    height_pt: float
    rotation: int
    vector_paths: int
    text_chars: int
    image_coverage: float
    text: str
    paper_size: str | None  # A0–A4 om sidan har en standardstorlek

    @property
    def has_text_layer(self) -> bool:
        return self.text_chars >= int(load_thresholds().get("ingest.min_text_chars_for_text_layer"))


def paper_size(width_pt: float, height_pt: float) -> str | None:
    cfg = load_documents_config()
    short, long_ = sorted((width_pt * MM_PER_PT, height_pt * MM_PER_PT))
    for name, (w, h) in cfg.paper_sizes_mm.items():
        if abs(short - w) <= cfg.paper_size_tolerance_mm and abs(long_ - h) <= cfg.paper_size_tolerance_mm:
            return name
    return None


def page_features(page: pymupdf.Page) -> PageFeatures:
    page_rect = page.rect
    area = page_rect.width * page_rect.height or 1.0
    covered = 0.0
    for info in page.get_image_info():
        covered += (rect(info["bbox"]) & page_rect).get_area()
    text = str(page_text(page, "text"))
    return PageFeatures(
        page_no=page.number + 1,
        width_pt=page_rect.width,
        height_pt=page_rect.height,
        rotation=page.rotation,
        vector_paths=len(page.get_drawings()),
        text_chars=len(text.strip()),
        image_coverage=min(covered / area, 1.0),
        text=text,
        paper_size=paper_size(page_rect.width, page_rect.height),
    )


def page_format(f: PageFeatures) -> PageFormat:
    th = load_thresholds()
    raster = f.image_coverage >= th.get("ingest.raster_min_image_coverage")
    if raster and f.vector_paths <= th.get("ingest.raster_max_vector_paths"):
        return "pdf_raster"
    if raster:
        return "pdf_mixed"  # vektorer ovanpå ett rasterunderlag (t.ex. skannat A-underlag)
    return "pdf_vector"


def render_png(page: pymupdf.Page, dpi: int, clip: pymupdf.Rect | None = None) -> bytes:
    return png_bytes(page.get_pixmap(dpi=dpi, clip=clip, alpha=False))
