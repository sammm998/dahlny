"""Syntetiska PDF:er för tester (inga verkliga handlingar i repot)."""

from __future__ import annotations

import io

import pymupdf

A4 = (595.0, 842.0)
A1 = (2384.0, 1684.0)


def _text(page: pymupdf.Page, x: float, y: float, text: str, size: float = 9) -> None:
    page.insert_text((x, y), text, fontsize=size)


def tb_document(pages: int = 3) -> bytes:
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for i in range(pages):
        page = doc.new_page(width=A4[0], height=A4[1])
        if i == 1:
            _text(page, 60, 80, "INNEHÅLLSFÖRTECKNING")
            _text(page, 60, 100, "52 FÖRSÖRJNINGSSYSTEM ......... 7")
            continue
        _text(page, 60, 60, "12.4 TEKNISK BESKRIVNING")
        _text(page, 60, 75, "Uppdragsnummer: 70250105")
        _text(page, 60, 100, "KOD    TEXT    MÄNGD    ENHET")
        _text(page, 60, 120, "PNU.311  Ledningar av icke ytbehandlade raka kopparrör")
        if i == 2:
            _text(page, 60, 140, "Ritningar är förtecknade i separat handlings-/ritningsförteckning.")
    return bytes(doc.tobytes())  # type: ignore[no-untyped-call]


def drawing_set(*, list_rows: list[tuple[str, str, str]], drawing_pages: int) -> bytes:
    """Förteckning (A4, med textlager) + ritningssidor (A1, titelblock utan textlager som på CAD-plottar)."""
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=A4[0], height=A4[1])
    _text(page, 203, 62, "12.4 RITNINGSFÖRTECKNING")
    _text(page, 422, 90, "UPPDRAG NR")
    _text(page, 496, 102, "70250105")
    y = 159.0
    for x, word in ((61, "RITNINGSNUMMER"), (175, "STAT"), (203, "RITNINGENS INNEHÅLL"), (380, "SKALA"),
                    (422, "RITNINGSDATUM")):  # fmt: skip
        _text(page, x, y, word, 7)
    for i, (no, title, scale) in enumerate(list_rows):
        y = 232.0 + i * 18.5
        for x, word in ((61, no), (175, "BH"), (203, title), (380, scale), (422, "2025-09-15")):
            _text(page, x, y, word, 7)
    _text(page, 117, 794, "Bengt Dahlgren Karlstad AB, Blockgatan 10, Karlstad", 7)
    for n in range(drawing_pages):
        p = doc.new_page(width=A1[0], height=A1[1])
        for k in range(80 + n):  # vektorer: en ritning har många banor; olika antal per blad
            p.draw_line((100 + k * 10, 200), (100 + k * 10, 900))
        # titelblockets ram, olika per blad (texten är ritad som linjer på riktiga CAD-plottar)
        p.draw_rect((2050 + n * 5, 1400, 2380, 1680))
    return bytes(doc.tobytes())  # type: ignore[no-untyped-call]


def raster_page() -> bytes:
    """En sida som bara är en inskannad bild."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 280), False)  # type: ignore[no-untyped-call]
    pix.clear_with(200)  # type: ignore[no-untyped-call]
    img = pix.tobytes("png")  # type: ignore[no-untyped-call]
    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    page = doc.new_page(width=A4[0], height=A4[1])
    page.insert_image(page.rect, stream=io.BytesIO(img).getvalue())  # type: ignore[no-untyped-call]
    return bytes(doc.tobytes())  # type: ignore[no-untyped-call]
