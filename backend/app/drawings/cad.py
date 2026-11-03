"""Väg B (DXF/DWG) och väg A (IFC) – SPEC 6.4.1–6.4.2.

**Väg B, DXF:** linjer och polylinjer per lager; enheten ur `$INSUNITS` (meter/millimeter/centimeter). Ett
lager
mappas till rörbeteckning när lagernamnet innehåller en beteckning som `label_grammar.yaml` känner
(`V-KV01-K1-15`),
eller via en stilprofils lagerkarta (`layer_map`, SPEC 8). Övriga lager räknas inte – ett lager utan känd
betydelse
gissas aldrig (T7-mappningen är en senare väg). Längd = summan av segmentens längd, i meter, exakt.
DWG konverteras först till DXF med ODA File Converter eller LibreDWG (`dwg2dxf`); saknas konverteraren säger
felet det.

**Väg A, IFC:** `IfcPipeSegment` med systemtillhörighet (`IfcSystem`/`IfcDistributionSystem` via
`IfcRelAssignsToGroup`) och längd ur mängdegenskaper (`Qto_PipeSegmentBaseQuantities.Length`) eller ur
geometrins axel. Dimension ur `NominalDiameter` i egenskapsuppsättningen när den finns.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from app.config.settings import load_label_grammar

INSUNITS_TO_M = {0: None, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0}


class CadError(RuntimeError):
    pass


@dataclass
class CadRun:
    system: str | None
    designation: str | None
    dim: str | None
    length_m: float
    source: str  # lager eller IFC-GlobalId
    method: str  # dxf_layer | ifc_quantity | ifc_axis


def _designation_in(name: str, layer_map: dict[str, str] | None) -> str | None:
    if layer_map and name in layer_map:
        return layer_map[name]
    pat = re.compile(load_label_grammar().pipe.pattern)
    for token in re.split(r"[_\s|]+", name.upper()):
        for start in range(len(token)):
            m = pat.fullmatch(token[start:])
            if m and "-" in token[start:] and any(c.isdigit() for c in token[start:]):
                return token[start:]
    return None


def _split(designation: str) -> tuple[str, str | None]:
    parts = designation.split("-")
    dim = parts[-1] if len(parts) >= 3 and parts[-1][:1].isdigit() else None
    return parts[0], dim


def read_dxf(path: Path, layer_map: dict[str, str] | None = None) -> tuple[list[CadRun], list[str]]:
    import ezdxf

    doc = ezdxf.readfile(str(path))
    factor = INSUNITS_TO_M.get(int(doc.header.get("$INSUNITS", 0)))
    if factor is None:
        raise CadError(
            "DXF-filen anger ingen enhet ($INSUNITS) – mängden kan inte räknas i meter utan att gissa"
        )
    lengths: dict[str, float] = {}
    for e in doc.modelspace():
        layer = e.dxf.layer
        if e.dxftype() == "LINE":
            s, t = e.dxf.start, e.dxf.end
            seg = math.dist((s.x, s.y, s.z), (t.x, t.y, t.z))
        elif e.dxftype() == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points("xy")]
            if e.closed:
                pts.append(pts[0])
            seg = sum(math.dist(a, b) for a, b in pairwise(pts))
        else:
            continue
        lengths[layer] = lengths.get(layer, 0.0) + seg
    runs, skipped = [], []
    for layer, units in sorted(lengths.items()):
        des = _designation_in(layer, layer_map)
        if des is None:
            skipped.append(layer)
            continue
        system, dim = _split(des)
        runs.append(CadRun(system, des, dim, round(units * factor, 6), layer, "dxf_layer"))
    return runs, skipped


def dwg_to_dxf(path: Path) -> Path:
    tool = shutil.which("dwg2dxf") or shutil.which("ODAFileConverter")
    if tool is None:
        raise CadError(
            "DWG kräver en konverterare till DXF (LibreDWG `dwg2dxf` eller ODA File Converter) – "
            "ingen hittades. Be konsulten om DXF eller installera konverteraren."
        )
    out = Path(tempfile.mkdtemp()) / (path.stem + ".dxf")
    subprocess.run([tool, str(path), "-o", str(out)], check=True, capture_output=True, timeout=300)
    return out


def read_ifc(path: Path) -> list[CadRun]:
    import ifcopenshell
    import ifcopenshell.util.element as ue

    model = ifcopenshell.open(str(path))
    system_of: dict[int, str] = {}
    for rel in model.by_type("IfcRelAssignsToGroup"):
        group = rel.RelatingGroup
        if group.is_a("IfcSystem"):
            for obj in rel.RelatedObjects:
                system_of[obj.id()] = group.Name
    runs = []
    for seg in model.by_type("IfcPipeSegment"):
        psets = ue.get_psets(seg)
        length = None
        method = "ifc_quantity"
        for name, props in psets.items():
            if "Length" in props and ("Qto" in name or "Quantities" in name):
                length = float(props["Length"])
        if length is None:
            method = "ifc_axis"
            length = _axis_length(seg)
        dim = None
        for props in psets.values():
            if "NominalDiameter" in props:
                dim = format(float(props["NominalDiameter"]), "g")
        system = system_of.get(seg.id())
        unit = _length_unit(model)
        runs.append(CadRun(system, seg.Name, dim, round((length or 0.0) * unit, 6), seg.GlobalId, method))
    return runs


def _length_unit(model: object) -> float:
    import ifcopenshell.util.unit as uu

    return float(uu.calculate_unit_scale(model))


def _axis_length(seg: object) -> float:
    rep = getattr(seg, "Representation", None)
    if rep is None:
        return 0.0
    for r in rep.Representations:
        for item in r.Items:
            if item.is_a("IfcExtrudedAreaSolid"):
                return float(item.Depth)
            if item.is_a("IfcPolyline"):
                pts = [p.Coordinates for p in item.Points]
                return sum(math.dist(a, b) for a, b in pairwise(pts))
    return 0.0
