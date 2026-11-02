"""Sidklassning och titelblock (SPEC 6.1.4–5), med två oberoende vägar.

Sidklassning: deterministiska regler på textlagret (config/documents.yaml) och AI-uppgiften T1 på
översiktsbilden. Överens → hög konfidens; oense → granskning; bara en väg → den vägens konfidens.

Titelblock: textlagret i titelblockets område (när det finns) och AI-uppgiften T2 på ett renderat utsnitt.
Modellens fält kontrolleras deterministiskt: ritningsnummer och skala tolkas med mönstren i documents.yaml,
aldrig med modellens egen tolkning. Fält som inte går igenom kontrollen blir null + flagga.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pymupdf

from app.ai.client import AIClient, AIError
from app.ai.datatypes import ContentPart, ImagePart, ProviderError, ProviderNotConfigured, TextPart
from app.ai.schemas.classify import PageClassification, PageKind, TitleBlockReading
from app.classify.patterns import ScaleRatio, dates, drawing_numbers, project_number, scale_ratios
from app.config.settings import load_documents_config, load_thresholds
from app.ingest.pdf_pages import PageFeatures, render_png
from app.ingest.pdf_typed import page_textbox, rect

DRAWING_KINDS: frozenset[str] = frozenset({"plan", "schematic", "section", "detail", "legend_only"})
AI_UNAVAILABLE = (ProviderNotConfigured, ProviderError, AIError)


@dataclass(frozen=True)
class KindDecision:
    kind: PageKind | None
    confidence: float
    needs_review: bool
    rule_kind: str | None
    ai_kind: str | None
    ai_confidence: float | None
    reasons: list[str] = field(default_factory=list)
    ai_run_id: uuid.UUID | None = None


@dataclass(frozen=True)
class TitleBlock:
    drawing_no: str | None
    title_lines: list[str]
    level_name: str | None
    scale_text: str | None
    scales: list[ScaleRatio]
    project_no: str | None
    date: str | None
    revision: str | None
    consultant: str | None
    confidence: float
    needs_review: bool
    method: str  # text_layer | vision | text_layer+vision | none
    flags: list[str] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    ai_run_id: uuid.UUID | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "drawing_no": self.drawing_no,
            "title_lines": self.title_lines,
            "level_name": self.level_name,
            "scale_text": self.scale_text,
            "scales": [s.text for s in self.scales],
            "project_no": self.project_no,
            "date": self.date,
            "revision": self.revision,
            "consultant": self.consultant,
            "confidence": self.confidence,
            "needs_review": self.needs_review,
            "method": self.method,
            "flags": self.flags,
            "bbox": list(self.bbox) if self.bbox else None,
            "ai_run_id": str(self.ai_run_id) if self.ai_run_id else None,
        }


# --------------------------------------------------------------------------- sidklassning


def rule_kind(text: str) -> str | None:
    upper = text.upper()
    for rule in load_documents_config().page_kind_rules:
        any_ok = not rule.any_text or any(t.upper() in upper for t in rule.any_text)
        all_ok = all(t.upper() in upper for t in rule.all_text)
        if any_ok and all_ok:
            return rule.kind
    return None


def overview_png(page: pymupdf.Page) -> bytes:
    th = load_thresholds()
    max_px = th.get("ingest.overview_max_px")
    long_side_pt = max(page.rect.width, page.rect.height)
    dpi = min(int(th.get("ingest.render_overview_dpi")), int(max_px * 72 / long_side_pt))
    return render_png(page, max(dpi, 1))


def classify_page(
    page: pymupdf.Page,
    features: PageFeatures,
    ai: AIClient | None,
    *,
    title_block_text: str | None = None,
    project_id: uuid.UUID | None = None,
) -> KindDecision:
    th = load_thresholds()
    rule = rule_kind(features.text) if features.has_text_layer else None
    reasons: list[str] = []
    ai_value: PageClassification | None = None
    run_id = None
    accepted = False
    if ai is not None:
        chars = int(th.get("ingest.classify_text_chars"))
        inputs: list[ContentPart] = [
            TextPart(
                f"Sidans textlager (första {chars} tecken):\n{features.text[:chars] or '(inget textlager)'}"
            ),
            TextPart(f"Titelblockets text: {title_block_text or 'okänd'}"),
            ImagePart(overview_png(page), label=f"page{features.page_no}_overview"),
        ]
        min_conf = th.get("classify.ai_min_confidence")
        try:
            result = ai.structured_result(
                "T1",
                inputs,
                PageClassification,
                project_id=project_id,
                accept=lambda r: r.confidence >= min_conf,
            )
            ai_value, run_id, accepted = result.value, result.run_id, result.accepted
        except AI_UNAVAILABLE as exc:
            reasons.append(f"AI-klassning saknas: {exc}")

    auto = th.get("classify.auto_accept_confidence")
    if rule and ai_value:
        if ai_value.kind == rule:
            conf = th.get("classify.agreement_confidence")
            return KindDecision(rule, conf, False, rule, ai_value.kind, ai_value.confidence, reasons, run_id)
        reasons.append(f"Regeln säger {rule}, T1 säger {ai_value.kind} ({ai_value.reason})")
        return KindDecision(None, 0.0, True, rule, ai_value.kind, ai_value.confidence, reasons, run_id)
    if rule:
        conf = th.get("classify.rule_confidence")
        return KindDecision(rule, conf, conf < auto, rule, None, None, reasons)  # type: ignore[arg-type]
    if ai_value:
        if not accepted:
            reasons.append(f"T1 under konfidenströskeln: {ai_value.reason}")
        conf = ai_value.confidence
        return KindDecision(
            ai_value.kind, conf, conf < auto or not accepted, None, ai_value.kind, conf, reasons, run_id
        )
    reasons.append("Ingen regel träffade och ingen AI-klassning – sidan måste klassas manuellt")
    return KindDecision(None, 0.0, True, None, None, None, reasons)


# --------------------------------------------------------------------------- titelblock


def _clip(page: pymupdf.Page, region: tuple[float, float, float, float]) -> pymupdf.Rect:
    r = page.rect
    x0, y0, x1, y1 = region
    return rect((r.width * x0, r.height * y0, r.width * x1, r.height * y1))


def _clean_drawing_no(value: str | None, flags: list[str]) -> str | None:
    if not value:
        return None
    found = drawing_numbers(value.strip().upper())
    if len(found) == 1:
        return found[0]
    flags.append(f"drawing_no_not_matching_pattern:{value!r}")
    return None


def read_title_block(
    page: pymupdf.Page,
    features: PageFeatures,
    ai: AIClient | None,
    *,
    project_id: uuid.UUID | None = None,
) -> TitleBlock:
    cfg = load_documents_config()
    th = load_thresholds()
    flags: list[str] = []
    clip = _clip(page, cfg.title_block.regions[0])
    # Väg 1: textlagret i titelblockets område (finns på vissa ritningar, inte på CAD-plottar med SHX-text)
    layer_text = page_textbox(page, clip)
    layer_numbers = drawing_numbers(layer_text)
    layer_scales = scale_ratios(layer_text)
    layer_project = project_number(layer_text)
    layer_dates = dates(layer_text)

    # Väg 2: T2 på renderat utsnitt; nästa region om titelblocket inte hittades
    reading: TitleBlockReading | None = None
    run_id = None
    accepted = False
    if ai is not None:
        min_conf = th.get("classify.ai_min_confidence")
        for region in cfg.title_block.regions:
            clip = _clip(page, region)
            png = render_png(page, cfg.title_block.dpi, clip)
            try:
                result = ai.structured_result(
                    "T2",
                    [ImagePart(png, label=f"page{features.page_no}_title_block")],
                    TitleBlockReading,
                    project_id=project_id,
                    accept=lambda r: r.confidence >= min_conf and not r.uncertain_fields,
                )
            except AI_UNAVAILABLE as exc:
                flags.append(f"ai_unavailable:{type(exc).__name__}")
                break
            reading, run_id, accepted = result.value, result.run_id, result.accepted
            if reading.found:
                break

    ai_no = _clean_drawing_no(reading.drawing_no, flags) if reading and reading.found else None
    ai_scales = scale_ratios(reading.scale_text or "") if reading and reading.found else []
    if reading and reading.found and reading.scale_text and not ai_scales and "-" not in reading.scale_text:
        flags.append(f"scale_text_not_parsed:{reading.scale_text!r}")

    # Sammanvägning per fält: båda vägarna överens → säkert; olika → null + flagga; en väg → den vägen
    def pick(name: str, layer: Any, vision: Any) -> Any:
        if layer and vision and layer != vision:
            flags.append(f"{name}_conflict:{layer!r}!={vision!r}")
            return None
        return layer or vision

    drawing_no = pick("drawing_no", layer_numbers[0] if len(layer_numbers) == 1 else None, ai_no)
    scales = layer_scales or ai_scales
    if layer_scales and ai_scales and [s.text for s in layer_scales] != [s.text for s in ai_scales]:
        flags.append("scale_conflict")
        scales = []
    project_no = pick(
        "project_no",
        layer_project,
        (reading.project_no or "").strip() or None if reading and reading.found else None,
    )
    date_value = pick(
        "date",
        layer_dates[0] if layer_dates else None,
        next(iter(dates(reading.date or "")), None) if reading and reading.found else None,
    )
    methods = [m for m, used in (("text_layer", bool(layer_text.strip())), ("vision", bool(reading))) if used]
    if reading and reading.found:
        conf = (
            reading.confidence
            if accepted
            else min(reading.confidence, th.get("classify.ai_min_confidence") - 0.01)
        )
        if layer_numbers and drawing_no:
            conf = max(conf, th.get("classify.agreement_confidence"))
    elif layer_numbers:
        conf = th.get("classify.rule_confidence")
    else:
        conf = 0.0
        flags.append("title_block_not_read")
    needs_review = conf < th.get("classify.auto_accept_confidence") or any("conflict" in f for f in flags)
    return TitleBlock(
        drawing_no=drawing_no,
        title_lines=list(reading.title_lines) if reading and reading.found else [],
        level_name=reading.level_name if reading and reading.found else None,
        scale_text=reading.scale_text
        if reading and reading.found
        else (" ".join(s.text for s in scales) or None),
        scales=scales,
        project_no=project_no,
        date=date_value,
        revision=reading.revision if reading and reading.found else None,
        consultant=reading.consultant if reading and reading.found else None,
        confidence=round(conf, 3),
        needs_review=needs_review,
        method="+".join(methods) or "none",
        flags=sorted(set(flags)),
        bbox=(clip.x0, clip.y0, clip.x1, clip.y1),
        ai_run_id=run_id,
    )
