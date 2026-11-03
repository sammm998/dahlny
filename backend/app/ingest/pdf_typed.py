"""Typade omslag kring de PyMuPDF-anrop som saknar typannoteringar (mypy --strict).

Samlade här så att undantagen från typkontrollen finns på ett ställe i stället för spridda i koden.
"""

from __future__ import annotations

from typing import Any

import pymupdf


def page_text(page: pymupdf.Page, mode: str = "text") -> Any:
    return page.get_text(mode)  # type: ignore[no-untyped-call]


def page_words(page: pymupdf.Page) -> list[tuple[float, float, float, float, str]]:
    return [(w[0], w[1], w[2], w[3], w[4]) for w in page_text(page, "words")]


def rect(bbox: Any) -> pymupdf.Rect:
    return pymupdf.Rect(bbox)  # type: ignore[no-untyped-call]


def png_bytes(pix: pymupdf.Pixmap) -> bytes:
    data: bytes = pix.tobytes("png")  # type: ignore[no-untyped-call]
    return data


def page_textbox(page: pymupdf.Page, clip: pymupdf.Rect) -> str:
    return str(page.get_textbox(clip))


def open_pdf(data: bytes) -> pymupdf.Document:
    return pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]


def new_pdf() -> pymupdf.Document:
    return pymupdf.open()  # type: ignore[no-untyped-call]


def pdf_bytes(doc: pymupdf.Document) -> bytes:
    data: bytes = doc.tobytes()  # type: ignore[no-untyped-call]
    return data
