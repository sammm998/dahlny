"""Väg B (DXF) och väg A (IFC) på syntetiska filer med exakt facit (SPEC 6.4.1–6.4.2, fas 9)."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import ifcopenshell
import ifcopenshell.api
import pytest

from app.drawings.cad import CadError, read_dxf, read_ifc


def test_dxf_lengths_per_layer_in_metres_exactly(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4  # mm
    msp = doc.modelspace()
    msp.add_line((0, 0), (3000, 0), dxfattribs={"layer": "V-KV01-K1-15"})
    msp.add_line((3000, 0), (3000, 4000), dxfattribs={"layer": "V-KV01-K1-15"})
    msp.add_lwpolyline([(0, 0), (1000, 0), (1000, 500)], dxfattribs={"layer": "V_S01-P2-110"})
    msp.add_line((0, 0), (99999, 0), dxfattribs={"layer": "A-VAGG"})  # okänt lager räknas inte
    path = tmp_path / "rit.dxf"
    doc.saveas(path)
    runs, skipped = read_dxf(path)
    by = {r.designation: r for r in runs}
    assert by["KV01-K1-15"].length_m == 7.0 and by["KV01-K1-15"].dim == "15"
    assert by["S01-P2-110"].length_m == 1.5 and by["S01-P2-110"].system == "S01"
    assert skipped == ["A-VAGG"]
    assert read_dxf(path, {"A-VAGG": "KV01-K1-28"})[0][0].length_m == 99.999  # stilprofilens lagerkarta


def test_dxf_without_units_is_refused(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 0
    doc.modelspace().add_line((0, 0), (1, 0), dxfattribs={"layer": "KV01-K1-15"})
    doc.saveas(tmp_path / "x.dxf")
    with pytest.raises(CadError, match="enhet"):
        read_dxf(tmp_path / "x.dxf")


def test_ifc_pipe_segments_with_system_and_quantity(tmp_path: Path) -> None:
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="Test")
    ifcopenshell.api.run("unit.assign_unit", f, length={"is_metric": True, "raw": "METERS"})
    system = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcDistributionSystem", name="KV01")
    segs = []
    for name, length, dn in (("KV01-K1-15", 4.25, 15), ("KV01-K1-28", 1.75, 28)):
        seg = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcPipeSegment", name=name)
        q = ifcopenshell.api.run("pset.add_qto", f, product=seg, name="Qto_PipeSegmentBaseQuantities")
        ifcopenshell.api.run("pset.edit_qto", f, qto=q, properties={"Length": length})
        p = ifcopenshell.api.run("pset.add_pset", f, product=seg, name="Pset_PipeSegmentTypeCommon")
        ifcopenshell.api.run("pset.edit_pset", f, pset=p, properties={"NominalDiameter": float(dn)})
        segs.append(seg)
    ifcopenshell.api.run("system.assign_system", f, products=segs, system=system)
    del project
    path = tmp_path / "m.ifc"
    f.write(str(path))
    runs = {r.designation: r for r in read_ifc(path)}
    assert runs["KV01-K1-15"].length_m == 4.25 and runs["KV01-K1-15"].system == "KV01"
    assert runs["KV01-K1-28"].dim == "28" and runs["KV01-K1-28"].method == "ifc_quantity"
