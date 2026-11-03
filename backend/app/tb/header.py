"""Projektuppgifter ur TB:ns sidhuvud: projektnamn och beställare under rubriken PROJEKT (SPEC 6.6 mailmall).

Sidhuvudet skriver fältets rubrik (`PROJEKT`) och raderna under den i samma kolumn. Sista raden är beställaren
när
fältet har mer än en rad. Det är ett förslag – användaren rättar det i projektvyn.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingest.pdf_typed import open_pdf, page_text
from app.tb.layout import _spans, find_columns

HEADER_LABELS = {
    "PROJEKT",
    "DATUM",
    "SIDA",
    "HANDLÄGGARE",
    "UPPDRAGSNUMMER",
    "DOKUMENT",
    "STATUS",
    "HANDLING",
    "ÄNDRINGSDATUM",
    "REVIDERING",
}
COLUMN_TOL_PT = 3.0


@dataclass
class ProjectInfo:
    name: str | None
    customer: str | None
    project_no: str | None
    consultant: str | None = None


def project_info(pdf_bytes: bytes, project_no: str | None = None) -> ProjectInfo:
    with open_pdf(pdf_bytes) as doc:
        for page in doc:
            spans = _spans(page)
            cols = find_columns(spans)
            if cols is None:
                continue
            label = next(
                (s for s in spans if s.text.upper() == "PROJEKT" and s.y0 < cols.header_bottom), None
            )
            if label is None:
                continue
            below = sorted(
                (
                    s
                    for s in spans
                    if abs(s.x0 - label.x0) <= COLUMN_TOL_PT
                    and label.y1 <= s.y0 < cols.header_bottom
                    and s.text.upper() not in HEADER_LABELS
                ),
                key=lambda s: s.y0,
            )
            texts = [s.text for s in below]
            first = str(page_text(page)).strip().split("\n")
            consultant = first[0].strip() if first else None
            if not texts:
                return ProjectInfo(None, None, project_no, consultant)
            name = " ".join(texts[:-1]) if len(texts) > 1 else texts[0]
            customer = texts[-1] if len(texts) > 1 else None
            return ProjectInfo(name, customer, project_no, consultant)
    return ProjectInfo(None, None, project_no)
