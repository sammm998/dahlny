"""Leverantörsförfrågningar (SPEC 6.6): utkast per leverantör, med Excelbilaga, som .eml-fil.

Rader med utfallet `request` grupperas per leverantör (registrets leverantör, annars postens fabrikat; okänd →
"Okänd leverantör", användaren väljer). Frågorna tas ur avvikelserna som gäller raderna
(ACCESSORY_NOT_CONFIRMED, TB_SELF_CONTRADICTION, UNDEFINED_VALUE), optioner (OPTION_REQUIRED) står för sig. De
tekniska kraven citeras ordagrant ur TB.

T9 skriver mailets löptext. Allt T9 skriver prövas deterministiskt: varje beteckning ska finnas med, och varje
tal i
texten ska finnas i raderna, kraven eller frågorna. Klarar texten inte det används mallen i stället (flaggat)
–
ett mail med ett påhittat antal eller mått lämnar aldrig systemet. Inget skickas: utkastet blir en fil, eller
ett
utkast i användarens brevlåda när en adapter är påslagen (app/requests/mailbox.py).
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from email.message import EmailMessage
from email.utils import formatdate

from pydantic import BaseModel, Field

from app.ai.client import AIClient, AIError
from app.articles.match import MatchResult
from app.rules.catalog import DeviationDraft
from app.tb.extract import ItemDraft
from app.tb.header import ProjectInfo

QUESTION_RULES = (
    "ACCESSORY_NOT_CONFIRMED",
    "TB_SELF_CONTRADICTION",
    "UNDEFINED_VALUE",
    "CONFLICTING_REQUIREMENTS",
)
UNKNOWN_SUPPLIER = "Okänd leverantör"
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass
class RequestLine:
    designation: str
    description: str
    quantity: Decimal | None
    unit: str | None
    supplier_art_no: str | None
    requirements: str | None  # ordagrant ur TB


@dataclass
class RequestDraft:
    supplier: str
    project: ProjectInfo
    lines: list[RequestLine]
    questions: list[str]
    options: list[str]
    subject: str = ""
    body_md: str = ""
    flags: list[str] = field(default_factory=list)


def _mentions(d: DeviationDraft, designation: str) -> bool:
    return (
        bool(designation)
        and re.search(rf"(?<![A-Z0-9]){re.escape(designation)}(?![A-Z0-9])", d.message) is not None
    )


def build_requests(
    items: list[ItemDraft], results: list[MatchResult], deviations: list[DeviationDraft], project: ProjectInfo
) -> list[RequestDraft]:
    goods = [it for it in items if it.kind == "object"]
    by_supplier: dict[str, list[tuple[ItemDraft, MatchResult]]] = {}
    for it, r in zip(goods, results, strict=True):
        if r.outcome != "request":
            continue
        supplier = (r.article.supplier if r.article else None) or it.manufacturer or UNKNOWN_SUPPLIER
        by_supplier.setdefault(supplier, []).append((it, r))
    out = []
    for supplier, pairs in sorted(by_supplier.items()):
        lines = [
            RequestLine(
                designation=(
                    f"{it.parent_designation} (tillbehör)" if it.parent_designation else it.designation or ""
                ),
                description=it.description,
                quantity=it.quantity,
                unit=it.unit,
                supplier_art_no=(r.article.supplier_art_no if r.article else None) or it.article_no,
                requirements=it.requirements_text,
            )
            for it, r in pairs
        ]
        names = {it.designation or it.parent_designation or "" for it, _ in pairs}
        questions = [
            d.question or d.message
            for d in deviations
            if d.rule_id in QUESTION_RULES and any(_mentions(d, n) for n in names)
        ]
        options = [
            d.message
            for d in deviations
            if d.rule_id == "OPTION_REQUIRED" and any(_mentions(d, n) for n in names)
        ]
        draft = RequestDraft(
            supplier, project, lines, list(dict.fromkeys(questions)), list(dict.fromkeys(options))
        )
        draft.subject = f"Prisförfrågan {project.name or 'projekt'}" + (
            f", uppdrag {project.project_no}" if project.project_no else ""
        )
        out.append(draft)
    return out


def _qty(line: RequestLine) -> str:
    if line.quantity is None:
        return "enligt ritning"
    return f"{format(line.quantity.normalize(), 'f')} {line.unit or 'st'}"


def template_body(d: RequestDraft) -> str:
    """Mallen: används direkt utan AI, och när T9:s text inte klarar kontrollen."""
    p = d.project
    head = [
        "Hej,",
        "",
        f"Vi räknar på {p.name or 'ett projekt'}"
        + (f" åt {p.customer}" if p.customer else "")
        + (f" (uppdrag {p.project_no})" if p.project_no else "")
        + " och ber om pris och leveranstid på följande:",
        "",
    ]
    rows = []
    for ln in d.lines:
        rows.append(
            f"- **{ln.designation}** – {ln.description}, {_qty(ln)}"
            + (f", art.nr {ln.supplier_art_no}" if ln.supplier_art_no else "")
        )
        if ln.requirements:
            rows += [f"  > {r}" for r in ln.requirements.split("\n")]
    tail: list[str] = []
    if d.questions:
        tail += ["", "Frågor:", *[f"- {q}" for q in d.questions]]
    if d.options:
        tail += ["", "Optioner (prissätts separat):", *[f"- {o}" for o in d.options]]
    tail += ["", "Fyll gärna i pris och leveranstid i bifogad Excelfil.", "", "Med vänlig hälsning"]
    return "\n".join(head + rows + tail)


class T9Body(BaseModel):
    body_md: str = Field(description="Mailets text i markdown, på svenska")


def _allowed_numbers(d: RequestDraft) -> set[str]:
    src = [
        d.project.project_no or "",
        *(
            f"{ln.designation} {ln.description} {_qty(ln)} {ln.supplier_art_no or ''} {ln.requirements or ''}"
            for ln in d.lines
        ),
        *d.questions,
        *d.options,
    ]
    return {n.replace(",", ".") for s in src for n in NUMBER_RE.findall(s)}


def check_body(d: RequestDraft, body: str) -> list[str]:
    """Det T9 skrev får inte innehålla ett tal som inte finns i underlaget, och varje rad ska nämnas."""
    problems = [f"saknar {ln.designation}" for ln in d.lines if ln.designation.split(" ")[0] not in body]
    allowed = _allowed_numbers(d)
    problems += [
        f"tal utan källa: {n}" for n in NUMBER_RE.findall(body) if n.replace(",", ".") not in allowed
    ]
    for ln in d.lines:
        for r in (ln.requirements or "").split("\n"):
            if r.strip() and r.strip() not in body:
                problems.append(f"krav inte ordagrant: {r[:40]}")
    return problems


def compose(d: RequestDraft, ai: AIClient | None, project_id: uuid.UUID | None = None) -> RequestDraft:
    d.body_md = template_body(d)
    if ai is None:
        d.flags.append("template_without_ai")
        return d
    try:
        resp = ai.structured("T9", d.body_md, T9Body, project_id=project_id)
    except AIError as exc:
        d.flags.append(f"t9_failed:{type(exc).__name__}")
        return d
    problems = check_body(d, resp.body_md)
    if problems:
        d.flags.append("t9_rejected:" + "; ".join(problems[:5]))
        return d
    d.body_md = resp.body_md
    return d


def attachment_xlsx(d: RequestDraft) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Förfrågan"
    ws.append([f"Prisförfrågan – {d.project.name or ''}", "", "", "", "", ""])
    ws.append(["Beteckning", "Leverantörens art.nr", "Benämning", "Antal", "Enhet", "Pris", "Leveranstid"])
    for c in ws[2]:
        c.font = Font(bold=True)
    for ln in d.lines:
        ws.append(
            [
                ln.designation,
                ln.supplier_art_no or "",
                ln.description,
                float(ln.quantity) if ln.quantity is not None else "enl. ritning",
                ln.unit or "",
                "",
                "",
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _html(md: str) -> str:
    out = []
    for line in md.split("\n"):
        esc = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
        if line.startswith("  > "):
            out.append(f"<blockquote>{esc[8:]}</blockquote>")
        elif line.startswith("- "):
            out.append(f"<li>{esc[2:]}</li>")
        else:
            out.append(f"<p>{esc}</p>" if esc else "<br>")
    return "<html><body>" + "\n".join(out) + "</body></html>"


def to_eml(d: RequestDraft, to_address: str | None = None, from_address: str | None = None) -> bytes:
    """RFC 5322-utkast (öppnas i Outlook som ett osänt utkast via X-Unsent, och i Gmail/andra klienter som
    mail)."""
    msg = EmailMessage()
    msg["Subject"] = d.subject
    msg["To"] = to_address or ""
    if from_address:
        msg["From"] = from_address
    msg["Date"] = formatdate(localtime=True)
    msg["X-Unsent"] = "1"
    msg["X-VS-Kalkyl"] = f"utkast; leverantör {d.supplier}; skickas aldrig automatiskt"
    msg.set_content(d.body_md.replace("**", ""))
    msg.add_alternative(_html(d.body_md), subtype="html")
    name = re.sub(r"[^A-Za-z0-9ÅÄÖåäö_-]+", "_", f"forfragan_{d.supplier}") + ".xlsx"
    msg.add_attachment(
        attachment_xlsx(d),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=name,
    )
    return bytes(msg)
