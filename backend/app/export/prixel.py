"""Export till Prixel (SPEC 6.7): Excel, urklipp (tabbseparerat) och en API-stub.

ÖPPEN FRÅGA 1: Prixels importmöjligheter och fältens betydelse är inte bekräftade. Kolumnordningen följer
exempelraden i Bilaga A.6 och kan ändras i `config/prixel.yaml`; fält med okänd betydelse (pris, nettopris,
rabatt %, prisstatus) lämnas tomma. Rader grupperas per position: en rubrikrad med beteckningen, sedan
artikelrader,
sedan rader med kort produktdata som tas deterministiskt ur TB-posten (dimension och de krav som nämner
material
eller utlopp).
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.config.settings import load_prixel_config


@dataclass
class ExportLine:
    article_no: str | None
    name: str
    quantity: Decimal | None
    unit: str | None
    discount_group: str | None
    supplier: str | None
    outcome: str  # stock | virtual | request | uncertain
    description: list[str] = field(default_factory=list)


@dataclass
class ExportPosition:
    designation: str
    lines: list[ExportLine]


def describe(dimension: str | None, requirements_text: str | None) -> list[str]:
    cfg = load_prixel_config()
    out = [f"Dim. {dimension}."] if dimension else []
    for sentence in re.split(r"(?<=[.])\s+|\n", requirements_text or ""):
        s = sentence.strip()
        if s and any(k.lower() in s.lower() for k in cfg.description_keywords) and s not in out:
            out.append(s if s.endswith(".") else s + ".")
    return out[: cfg.description_max_lines]


def _num(v: Decimal | None) -> str:
    if v is None:
        return ""
    text = format(v.normalize(), "f")
    return text.replace(".", ",") if load_prixel_config().decimal_comma else text


def _cells(pos_no: int, ln: ExportLine) -> list[str]:
    cfg = load_prixel_config()
    values = {
        "pos": str(pos_no),
        "article_no": ln.article_no or "",
        "name": ln.name,
        "unit": cfg.unit_map.get(ln.unit or "", ln.unit or ""),
        "quantity": _num(ln.quantity),
        "discount_group": ln.discount_group or "",
        "supplier": ln.supplier or "",
    }
    return [values.get(c.key, "") for c in cfg.columns]


def rows(positions: Sequence[ExportPosition]) -> list[list[str]]:
    """Tabellen i Prixels radordning: rubrikrad per position, artikelrader, beskrivningsrader."""
    width = len(load_prixel_config().columns)
    out: list[list[str]] = []
    for p in positions:
        out.append([p.designation] + [""] * (width - 1))
        for i, ln in enumerate(p.lines, start=1):
            out.append(_cells(i, ln))
            out += [["", d] + [""] * (width - 2) for d in ln.description]
    return out


class PrixelExporter(Protocol):
    def export(self, positions: Sequence[ExportPosition]) -> bytes: ...


class ClipboardExporter:
    """Tabbseparerad text i radordning, att klistra in i Prixel."""

    def export(self, positions: Sequence[ExportPosition]) -> bytes:
        return "\n".join("\t".join(r).rstrip("\t") for r in rows(positions)).encode("utf-8")


class ExcelExporter:
    def export(self, positions: Sequence[ExportPosition]) -> bytes:
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Prixel"
        ws.append([c.title for c in load_prixel_config().columns])
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows(positions):
            ws.append(r)
            if r[0] and not r[1]:  # rubrikrad (position)
                ws.cell(ws.max_row, 1).font = Font(bold=True)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


class PrixelApiNotConfigured(RuntimeError):
    pass


class ApiExporter:
    """Stub tills Prixels API är bekräftat (SPEC 14 fråga 1)."""

    def export(self, positions: Sequence[ExportPosition]) -> bytes:
        raise PrixelApiNotConfigured(
            "Export direkt till Prixel via API är inte påslagen: Prixels API och fältformat är inte "
            "bekräftade "
            "(SPEC 14, fråga 1). Använd Excel- eller urklippsexporten tills vidare."
        )
