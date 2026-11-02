"""Fas 1: intag, sidklassning, titelblock och ritningsförteckning (SPEC 6.1).

    python -m app.pipeline.phase1 --project "Tvätthall Årjäng" fil1.pdf fil2.zip [--no-ai]

`analyze_files` gör analysen utan att skriva till databasen (bara AI-anropen loggas i ai_run); `persist`
sparar resultatet som Document, Page och Deviation. Korskontrollerna mot ritningsförteckningen och mot TB:s
uppdragsnummer ger avvikelser enligt SPEC 6.1.5–6.
"""

from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.ai.client import AIClient
from app.classify.drawing_list import DrawingList, parse_drawing_list
from app.classify.pages import DRAWING_KINDS, KindDecision, TitleBlock, classify_page, read_title_block
from app.classify.patterns import project_number
from app.config.settings import load_thresholds
from app.drawings.checks import declared_scale_for_page
from app.ingest.files import InputFile, expand
from app.ingest.pdf_pages import PageFeatures, page_features, page_format, render_png
from app.ingest.pdf_typed import open_pdf
from app.ingest.storage import Storage
from app.rules.catalog import DeviationDraft


@dataclass
class PageResult:
    page_no: int
    features: PageFeatures
    format: str
    kind: KindDecision
    title_block: TitleBlock | None = None
    drawing_list: DrawingList | None = None


@dataclass
class DocumentResult:
    file: InputFile
    pages: list[PageResult] = field(default_factory=list)
    project_no: str | None = None  # ur dokumentets egen text (TB-omslag, förteckning)

    @property
    def kind(self) -> str | None:
        kinds = {p.kind.kind for p in self.pages}
        return kinds.pop() if len(kinds) == 1 else None  # blandad PDF: sidorna bär typen


@dataclass
class Phase1Result:
    documents: list[DocumentResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    deviations: list[DeviationDraft] = field(default_factory=list)


def _ref(doc: DocumentResult, page: PageResult | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"filename": doc.file.filename, "sha256": doc.file.sha256}
    if page is not None:
        out["page"] = page.page_no
    out.update(extra)
    return out


def analyze_pdf(file: InputFile, ai: AIClient | None, project_id: uuid.UUID | None) -> DocumentResult:
    result = DocumentResult(file=file)
    with open_pdf(file.data) as pdf:
        result.project_no = project_number(pdf[0].get_textbox(pdf[0].rect)) if len(pdf) else None
        for page in pdf:
            features = page_features(page)
            decision = classify_page(page, features, ai, project_id=project_id)
            result.pages.append(PageResult(features.page_no, features, page_format(features), decision))
        _inherit_document_kind(result)
        # Andra varvet: titelblock och förteckning läses först när sidans typ är satt
        for pr in result.pages:
            page = pdf[pr.page_no - 1]
            if pr.kind.kind == "drawing_list":
                pr.drawing_list = parse_drawing_list(page)
            elif pr.kind.kind in DRAWING_KINDS or pr.kind.kind is None:
                pr.title_block = read_title_block(page, pr.features, ai, project_id=project_id)
    return result


def _inherit_document_kind(doc: DocumentResult) -> None:
    """En sida utan eget utslag (t.ex. TB:s innehållsförteckning) ärver dokumentets typ när nästan alla sidor
    delar den. En blandad PDF (förteckning + planer + schema) har ingen sådan majoritet och ärver inget."""
    th = load_thresholds()
    kinds = [p.kind.kind for p in doc.pages if p.kind.kind]
    if not kinds:
        return
    top = max(set(kinds), key=kinds.count)
    if kinds.count(top) / len(doc.pages) < th.get("classify.document_majority_fraction"):
        return
    for p in doc.pages:
        if p.kind.kind is None and p.kind.ai_kind is None:
            conf = th.get("classify.document_inherit_confidence")
            p.kind = replace(
                p.kind,
                kind=top,
                confidence=conf,
                needs_review=conf < th.get("classify.auto_accept_confidence"),
                reasons=[
                    *p.kind.reasons,
                    f"Ärver dokumentets typ {top} ({kinds.count(top)} av {len(doc.pages)} sidor)",
                ],
            )


def analyze_files(
    files: list[InputFile], ai: AIClient | None, project_id: uuid.UUID | None = None
) -> Phase1Result:
    out = Phase1Result()
    seen: set[str] = set()
    for f in files:
        if f.sha256 in seen:
            out.skipped.append(f"{f.filename}: dubblett (samma innehåll som en annan fil)")
            continue
        seen.add(f.sha256)
        if f.kind != "pdf":
            out.skipped.append(f"{f.filename}: {f.kind} hanteras i en senare fas (SPEC 6.4.1–6.4.4)")
            continue
        out.documents.append(analyze_pdf(f, ai, project_id))
    out.deviations = cross_check(out)
    return out


def cross_check(result: Phase1Result) -> list[DeviationDraft]:
    devs: list[DeviationDraft] = []
    lists = [(d, p) for d in result.documents for p in d.pages if p.drawing_list]
    drawings = [(d, p) for d in result.documents for p in d.pages if p.title_block]
    tb_projects = {d.project_no for d in result.documents if d.kind == "tb" and d.project_no}
    reference_project = next(iter(tb_projects), None) or next(
        (p.drawing_list.project_no for _, p in lists if p.drawing_list and p.drawing_list.project_no), None
    )

    listed = {
        e.drawing_no: (d, p, e)
        for d, p in lists
        if p.drawing_list
        for e in p.drawing_list.drawings
        if e.drawing_no
    }
    received = {
        p.title_block.drawing_no: (d, p) for d, p in drawings if p.title_block and p.title_block.drawing_no
    }
    unread = [(d, p) for d, p in drawings if p.title_block and not p.title_block.drawing_no]
    if lists:
        for no, (d, p, e) in listed.items():
            if no not in received:
                if unread:
                    message = (
                        f"Ritning {no} ({e.title}) finns i ritningsförteckningen men har inte identifierats "
                        f"bland mottagna sidor – {len(unread)} ritningssidor saknar läst ritningsnummer"
                    )
                    question = None
                else:
                    message = (
                        f"Ritning {no} ({e.title}) finns i ritningsförteckningen men har inte tagits emot"
                    )
                    question = f"Kan ni skicka ritning {no} ({e.title})?"
                devs.append(
                    DeviationDraft("DRAWING_LIST_MISMATCH", message, [_ref(d, p, drawing_no=no)], question)
                )
        for no, (d, p) in received.items():
            if no not in listed:
                devs.append(
                    DeviationDraft(
                        "DRAWING_LIST_MISMATCH",
                        f"Ritning {no} har tagits emot men finns inte i ritningsförteckningen",
                        [_ref(d, p, drawing_no=no)],
                    )
                )
    for no, (d, p) in received.items():
        tb = p.title_block
        assert tb is not None
        if reference_project and tb.project_no and tb.project_no != reference_project:
            devs.append(
                DeviationDraft(
                    "TITLEBLOCK_MISMATCH",
                    f"Ritning {no} anger uppdragsnummer {tb.project_no}, "
                    f"handlingarna i övrigt {reference_project}",
                    [_ref(d, p, drawing_no=no, field="project_no")],
                    question=f"Vilket uppdragsnummer gäller – {reference_project} eller {tb.project_no}?",
                )
            )
        if no in listed:
            _, _, entry = listed[no]
            list_scales = [s.text for s in entry.scales]
            block_scales = [s.text for s in tb.scales]
            effective = declared_scale_for_page(tb.scales, p.features.paper_size)
            if entry.no_scale and block_scales:
                devs.append(
                    DeviationDraft(
                        "TITLEBLOCK_MISMATCH",
                        f"Ritning {no}: förteckningen anger ingen skala ('-'), "
                        f"titelblocket {' '.join(block_scales)}",
                        [_ref(d, p, drawing_no=no, field="scale")],
                    )
                )
            elif (
                list_scales
                and effective
                and all(s.denominator != effective.denominator for s in entry.scales)
            ):
                devs.append(
                    DeviationDraft(
                        "TITLEBLOCK_MISMATCH",
                        f"Ritning {no}: förteckningen anger {', '.join(list_scales)}, "
                        f"titelblocket {effective.text} för sidans format ({p.features.paper_size})",
                        [_ref(d, p, drawing_no=no, field="scale")],
                    )
                )
    return devs


def persist(
    session: Session, project_id: uuid.UUID, result: Phase1Result, storage: Storage | None = None
) -> list[uuid.UUID]:
    """Sparar dokument, sidor (med titelblock) och avvikelser. Returnerar dokumentens id:n."""
    from app.db.models import Deviation, Document, Page

    th = load_thresholds()
    ids = []
    for d in result.documents:
        doc = Document(
            project_id=project_id,
            filename=d.file.filename,
            kind=d.kind,
            format=_document_format(d),
            sha256=d.file.sha256,
            pages=len(d.pages),
        )
        session.add(doc)
        session.flush()
        ids.append(doc.id)
        if storage is not None:
            storage.put(f"{project_id}/{d.file.sha256}/original.pdf", d.file.data)
        for p in d.pages:
            tb = p.title_block
            effective = declared_scale_for_page(tb.scales, p.features.paper_size) if tb else None
            session.add(
                Page(
                    document_id=doc.id,
                    page_no=p.page_no,
                    width_pt=p.features.width_pt,
                    height_pt=p.features.height_pt,
                    kind=p.kind.kind,
                    format=p.format,
                    title_block_json={
                        "kind_decision": _decision_json(p.kind),
                        **(tb.as_json() if tb else {}),
                    },
                    drawing_no=tb.drawing_no if tb else None,
                    level_name=tb.level_name if tb else None,
                    scale_declared=tb.scale_text if tb else None,
                    paper_size_declared=effective.paper if effective else None,
                )
            )
        if storage is not None:
            with open_pdf(d.file.data) as pdf:
                for page in pdf:
                    key = f"{project_id}/{d.file.sha256}/p{page.number + 1}_overview.png"
                    storage.put(key, render_png(page, int(th.get("ingest.render_overview_dpi"))))
    for dev in result.deviations:
        session.add(
            Deviation(
                project_id=project_id,
                rule_id=dev.rule_id,
                severity=dev.effective_severity,
                message=dev.message,
                refs=dev.refs,
                note=dev.question,
            )
        )
    session.flush()
    return ids


def _document_format(d: DocumentResult) -> str:
    formats = {p.format for p in d.pages}
    return formats.pop() if len(formats) == 1 else "pdf_mixed"


def _decision_json(k: KindDecision) -> dict[str, Any]:
    return {
        "kind": k.kind,
        "confidence": k.confidence,
        "needs_review": k.needs_review,
        "rule_kind": k.rule_kind,
        "ai_kind": k.ai_kind,
        "ai_confidence": k.ai_confidence,
        "reasons": k.reasons,
        "ai_run_id": str(k.ai_run_id) if k.ai_run_id else None,
    }


def load_inputs(paths: list[Path]) -> list[InputFile]:
    files: list[InputFile] = []
    for path in paths:
        files.extend(expand(path.name, path.read_bytes()))
    return files


def summary_lines(result: Phase1Result) -> list[str]:
    lines = []
    for d in result.documents:
        lines.append(
            f"{d.file.filename}: {len(d.pages)} sidor, typ {d.kind or 'blandad'}, uppdrag {d.project_no}"
        )
        for p in d.pages:
            tb = p.title_block
            extra = f" | {tb.drawing_no} {tb.scale_text} uppdrag {tb.project_no} ({tb.method})" if tb else ""
            flag = " [GRANSKA]" if p.kind.needs_review or (tb and tb.needs_review) else ""
            if len(d.pages) <= 6 or p.page_no == 1 or tb or p.kind.needs_review:
                head = (
                    f"  s{p.page_no} {p.format} {p.features.paper_size} → {p.kind.kind} ({p.kind.confidence})"
                )
                lines.append(head + extra + flag)
    lines += [f"HOPPAD ÖVER: {s}" for s in result.skipped]
    lines += [f"AVVIKELSE {d.effective_severity} {d.rule_id}: {d.message}" for d in result.deviations]
    return lines


def main(argv: list[str] | None = None) -> int:
    from app.db.models import Project
    from app.db.session import make_session_factory, session_scope

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--no-ai", action="store_true", help="bara deterministiska vägar")
    parser.add_argument(
        "--save", action="store_true", help="spara projekt, dokument och avvikelser i databasen"
    )
    args = parser.parse_args(argv)

    factory = make_session_factory()
    ai = None if args.no_ai else AIClient(factory)
    result = analyze_files(load_inputs(args.files), ai)
    print("\n".join(summary_lines(result)))
    if args.save:
        with session_scope(factory) as session:
            project = Project(name=args.project)
            session.add(project)
            session.flush()
            persist(session, project.id, result)
            print(f"Sparat som projekt {project.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
