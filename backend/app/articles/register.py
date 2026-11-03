"""Import av artikelregister (SPEC 6.3) ur CSV eller Excel, med kolumnmappning.

ÖPPEN FRÅGA 2 (affärssystem och exportformat) är inte besvarad, så importen känner igen kolumnerna på rubrik
(`config/articles.yaml`) och tar en egen mappning när rubrikerna är andra. Kolumner som inte känns igen sparas
i
`attributes`. En rad utan obligatoriska fält, eller med en lagerstatus som inte går att tolka, avvisas med
radnummer och skäl – den gissas aldrig.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import load_articles_config
from app.db.models import Article


@dataclass
class ArticleRow:
    dahl_art_no: str
    name: str
    stock_status: str  # stock | virtual | order
    rsk: str | None = None
    supplier: str | None = None
    supplier_art_no: str | None = None
    unit: str | None = None
    discount_group: str | None = None
    accessories: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class ImportResult:
    rows: list[ArticleRow]
    rejected: list[tuple[int, str]]  # (rad räknad från rubrikraden = 1, skäl)
    mapping: dict[str, str]  # fält → kolumnrubrik som användes
    unmapped: list[str]


def _key(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower())


def resolve_mapping(headers: list[str], override: dict[str, str] | None = None) -> dict[str, str]:
    cfg = load_articles_config()
    by_key = {_key(h): h for h in headers}
    mapping: dict[str, str] = {}
    for fld, names in cfg.columns.items():
        if override and fld in override:
            if override[fld] not in headers:
                raise ValueError(f"Kolumnen '{override[fld]}' för {fld} finns inte i filen")
            mapping[fld] = override[fld]
            continue
        hit = next((by_key[_key(n)] for n in names if _key(n) in by_key), None)
        if hit:
            mapping[fld] = hit
    missing = [f for f in cfg.required if f not in mapping]
    if missing:
        raise ValueError(
            "Registret saknar obligatoriska kolumner: "
            + ", ".join(missing)
            + ". Ange kolumnmappning för dem."
        )
    return mapping


def _stock(value: str) -> str | None:
    v = _key(value)
    for status, words in load_articles_config().stock_values.items():
        if v in {_key(w) for w in words}:
            return status
    return None


def _table(data: bytes, filename: str) -> tuple[list[str], list[list[str]]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        values = [
            ["" if c is None else str(c).strip() for c in row] for row in ws.iter_rows(values_only=True)
        ]
        rows = [r for r in values if any(r)]
    else:
        text = "\n".join(
            ln for ln in data.decode("utf-8-sig").splitlines() if not ln.lstrip().startswith("#")
        )
        dialect = csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=";,\t")
        rows = [
            [c.strip() for c in r]
            for r in csv.reader(io.StringIO(text), dialect)
            if any(c.strip() for c in r)
        ]
    rows = [r for r in rows if not r[0].startswith("#")]  # kommentarsrader (t.ex. TESTDATA-märkning)
    if not rows:
        raise ValueError("Registret är tomt")
    return rows[0], rows[1:]


def read_register(data: bytes, filename: str, mapping: dict[str, str] | None = None) -> ImportResult:
    headers, body = _table(data, filename)
    used = resolve_mapping(headers, mapping)
    col = {fld: headers.index(h) for fld, h in used.items()}
    extra = [h for h in headers if h not in used.values()]
    rows: list[ArticleRow] = []
    rejected: list[tuple[int, str]] = []
    for n, raw in enumerate(body, start=2):
        cells = raw + [""] * (len(headers) - len(raw))

        def get(fld: str, cells: list[str] = cells) -> str:
            return cells[col[fld]].strip() if fld in col else ""

        missing = [f for f in load_articles_config().required if not get(f)]
        if missing:
            rejected.append((n, "saknar " + ", ".join(missing)))
            continue
        status = _stock(get("stock_status"))
        if status is None:
            rejected.append((n, f"okänd lagerstatus '{get('stock_status')}'"))
            continue
        rsk = re.sub(r"\D", "", get("rsk")) or None
        if rsk is not None and len(rsk) != 7:
            rejected.append((n, f"RSK '{get('rsk')}' är inte sju siffror"))
            continue
        rows.append(
            ArticleRow(
                dahl_art_no=get("dahl_art_no"),
                name=get("name"),
                stock_status=status,
                rsk=rsk,
                supplier=get("supplier") or None,
                supplier_art_no=get("supplier_art_no") or None,
                unit=get("unit") or None,
                discount_group=get("discount_group") or None,
                accessories=[a.strip() for a in re.split(r"[;,]", get("accessories")) if a.strip()],
                attributes={h: cells[headers.index(h)] for h in extra if cells[headers.index(h)]},
            )
        )
    return ImportResult(rows, rejected, used, extra)


def save_register(session: Session, rows: list[ArticleRow]) -> tuple[int, int]:
    """Upsert på Dahl art.nr (nattlig synk: samma fil två gånger ändrar inget). Returnerar (nya,
    uppdaterade)."""
    existing = {a.dahl_art_no: a for a in session.scalars(select(Article))}
    new = updated = 0
    for r in rows:
        attrs: dict[str, Any] = {**r.attributes, "accessories": r.accessories}
        a = existing.get(r.dahl_art_no)
        if a is None:
            a = Article(id=uuid.uuid4(), dahl_art_no=r.dahl_art_no, name=r.name, stock_status=r.stock_status)
            session.add(a)
            new += 1
        else:
            updated += 1
        a.name, a.stock_status, a.rsk, a.supplier = r.name, r.stock_status, r.rsk, r.supplier
        a.supplier_art_no, a.unit, a.discount_group, a.attributes_json = (
            r.supplier_art_no,
            r.unit,
            r.discount_group,
            attrs,
        )
    session.flush()
    return new, updated
