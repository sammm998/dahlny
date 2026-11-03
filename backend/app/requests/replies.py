"""Priser ur leverantörssvar (SPEC 6.6 steg 5, T10). Varje pris måste stå i svaret; annars avvisas det."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.ai.client import AIClient
from app.requests.supplier import RequestDraft
from app.tb.extract import found_in


class ReplyLine(BaseModel):
    designation: str = Field(description="Radens beteckning som i förfrågan")
    price: float | None
    currency: str | None
    price_unit: str | None = Field(description="t.ex. 'st'")
    delivery_time: str | None = Field(description="Leveranstid ordagrant, t.ex. '2–3 veckor'")
    replacement: str | None = Field(description="Ersättningsartikel om leverantören föreslår en")
    quote: str | None = Field(description="Raden i svaret där priset står, ordagrant")


class T10Reply(BaseModel):
    lines: list[ReplyLine]


def extract_prices(
    draft: RequestDraft, reply_text: str, ai: AIClient, project_id: uuid.UUID | None = None
) -> list[dict[str, object]]:
    """reply_prices_json: en post per efterfrågad rad; ett pris utan ordagrant citat i svaret blir null +
    flagga."""
    asked = "\n".join(f"- {ln.designation}: {ln.description}" for ln in draft.lines)
    resp = ai.structured(
        "T10", f"# Efterfrågade rader\n{asked}\n\n# Svar\n{reply_text}", T10Reply, project_id=project_id
    )
    out: list[dict[str, object]] = []
    for ln in resp.lines:
        row = ln.model_dump()
        flags = []
        if ln.price is not None:
            price_txt = f"{ln.price:g}"
            ok = (
                ln.quote is not None
                and found_in(ln.quote, reply_text)
                and (
                    price_txt in ln.quote.replace(" ", "").replace(",", ".")
                    or price_txt.replace(".", ",") in ln.quote
                )
            )
            if not ok:
                row["price"] = None
                flags.append("price_not_in_reply")
        row["flags"] = flags
        row["status"] = "review"
        out.append(row)
    return out
