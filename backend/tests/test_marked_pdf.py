"""Markerad PDF (SPEC 6.4.6): summering först, rör färgade, standard-PDF; Excel-mängdlista."""

from __future__ import annotations

import io
import json
from pathlib import Path

from openpyxl import load_workbook

from app.drawings.estimates import FittingEstimate, InsulationRow
from app.drawings.quantities import QuantityRow
from app.drawings.source import DrawingTakeoff, SheetCoverage, SheetTakeoff
from app.export.marked_pdf import colour_key, key_of_identity, marked_pdf, quantity_xlsx
from app.ingest.pdf_typed import new_pdf, open_pdf, page_text, pdf_bytes


def _takeoff() -> DrawingTakeoff:
    sheet = SheetTakeoff(
        page=1,
        width_pt=600,
        height_pt=400,
        scale=None,
        coverage=SheetCoverage(page=1, drawn_m=10.0, confirmed_m=8.0, ambiguous_m=1.0, unowned_m=1.0),
        pipe_runs=[],
        symbols=[],
        legend=[],
        designations_read=[],
    )
    return DrawingTakeoff(source="t", source_version="t", input_sha256="x", sheets=[sheet])


def _row() -> QuantityRow:
    return QuantityRow(
        system="KV01",
        material="K1",
        material_source="etikett",
        material_confidence=None,
        dim="15",
        length_m=8.0,
        ambiguous_m=1.0,
        pages=[1],
        sub_rows=[],
    )


def test_the_engine_identity_and_the_row_share_a_colour() -> None:
    assert key_of_identity("KV01-K1-15|DN15") == colour_key("KV01", "15")


def test_marked_pdf_has_summary_first_and_colours_every_primitive(tmp_path: Path) -> None:
    doc = new_pdf()
    doc.new_page(width=600, height=400)
    drawing = pdf_bytes(doc)
    inv = tmp_path / "sheets" / "0"
    inv.mkdir(parents=True)
    prims = [
        {"x0": 10, "y0": 10, "x1": 200, "y1": 10, "state": "CONFIRMED", "identity": "KV01-K1-15|DN15"},
        {"x0": 10, "y0": 50, "x1": 200, "y1": 50, "state": "UNOWNED", "identity": None},
    ]
    (inv / "pipe-geometry-inventory.json").write_text(json.dumps({"primitives": prims}), encoding="utf-8")
    out = open_pdf(marked_pdf(drawing, tmp_path, _takeoff(), [_row()], "Testhall"))
    assert (
        len(out) == 2
        and "Mängdning: Testhall" in page_text(out[0])
        and "KV01 K1 15: 8.00 m" in page_text(out[0])
    )
    colours = {tuple(round(c, 2) for c in d["color"]) for d in out[1].get_drawings() if d.get("color")}
    assert (0.85, 0.05, 0.05) in colours and len(colours) == 2  # otilldelat rött + identitetens färg


def test_quantity_workbook_has_pipe_insulation_and_fitting_sheets() -> None:
    wb = load_workbook(
        io.BytesIO(
            quantity_xlsx(
                [_row()],
                [InsulationRow("KV01", "15", 8.0, "30 mm", "A", [])],
                [FittingEstimate("KV01|15", 3)],
            )
        )
    )
    assert wb.sheetnames == ["Rör", "Isolering", "Rördelar (uppskattning)"]
    assert wb["Rör"].cell(2, 5).value == 8.0 and wb["Rördelar (uppskattning)"].cell(2, 2).value == 3
