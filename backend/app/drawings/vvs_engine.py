"""vvs_engine som `DrawingQuantitySource` (SPEC 6.4.7).

Motorn körs som egen process (`vvs-takeoff analyze`) i sin egen miljö och lämnar JSON-artefakter. Den här
modulen läser artefakterna och mappar dem till VS-Kalkyls utkast:

- `quantities.json`-rader → `PipeRunDraft` (per beteckning och blad, med motorns rör-id:n),
- `physical-pipes.json` → evidenskedjan i `source_refs` (källbanor, ankare, frontier-skäl, bbox),
- stammar (`quantities.json.risers`) och objekttaggar (`vector-designations.json`) → `SymbolDraft`,
- `drawing-legend.json` → `LegendEntryDraft`, `reading-coverage.json` → otilldelad andel.

Mappningen räknar aldrig om en meter. Skala som motorn inte själv kallar verifierad, okända beteckningar och
okända konfidensnivåer blir flaggor som avstämningen (SPEC 6.5) tar hand om.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from app.config.settings import VvsEngineConfig, load_drawings_config, load_label_grammar, load_thresholds
from app.drawings.source import (
    DrawingSourceError,
    DrawingTakeoff,
    LegendEntryDraft,
    PipeRunDraft,
    SheetCoverage,
    SheetScale,
    SheetTakeoff,
    SourceRef,
    SymbolDraft,
)

METHOD = "vvs_engine"
PT_PER_MM = 72.0 / 25.4  # PDF-punkter per millimeter på papper (definition, inget gränsvärde)


def _read(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _bbox_of(geometry: list[list[list[float]]]) -> tuple[float, float, float, float] | None:
    points = [pt for line in geometry or [] for pt in line]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2))


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class VvsEngineSource:
    name = METHOD

    def __init__(self, config: VvsEngineConfig | None = None, command: list[str] | None = None) -> None:
        self.config = config or load_drawings_config().vvs_engine
        env_cmd = os.environ.get("VVS_ENGINE_CMD")
        self.command = command or (shlex.split(env_cmd) if env_cmd else list(self.config.command))

    # ------------------------------------------------------------------ körning

    def analyze(self, pdf_path: Path, work_dir: Path) -> DrawingTakeoff:
        out_dir = work_dir / "vvs_engine"
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            *self.command,
            "analyze",
            str(pdf_path),
            "--out",
            str(out_dir),
            "--name",
            pdf_path.stem,
            *self.rule_args(),
        ]
        try:
            # Kommandot kommer från config/miljö, aldrig från användarens indata.
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.config.timeout_s, check=False
            )
        except FileNotFoundError as exc:
            raise DrawingSourceError(
                f"vvs_engine hittas inte ({self.command[0]!r}). Installera motorn i egen miljö och sätt "
                "VVS_ENGINE_CMD, t.ex. '/opt/vvs-engine/bin/vvs-takeoff'."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise DrawingSourceError(f"vvs_engine tog mer än {self.config.timeout_s} s") from exc
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            raise DrawingSourceError(f"vvs_engine avslutades med kod {proc.returncode}: " + " | ".join(tail))
        return self.read_artifacts(out_dir, expected_sha256=_sha256(pdf_path))

    def rule_args(self) -> list[str]:
        """Motorns regler som VS-Kalkyls trösklar styr (drawings.yaml rules_from_thresholds)."""
        th = load_thresholds()
        out = []
        for rule_id, key in sorted(self.config.rules_from_thresholds.items()):
            out += ["--rule", f"{rule_id}={th.get(key)}"]
        for rule_id, keys in sorted(self.config.rules_from_thresholds_mm_to_pt.items()):
            mm = math.prod(float(th.get(k)) for k in keys)
            out += ["--rule", f"{rule_id}={round(mm * PT_PER_MM, 3)}"]
        return out

    # ------------------------------------------------------------------ artefakter

    def read_artifacts(self, out_dir: Path, *, expected_sha256: str | None = None) -> DrawingTakeoff:
        manifest = _read(out_dir / "freeze-manifest.json")
        schema = manifest.get("artifact_schema")
        if schema not in self.config.supported_artifact_schemas:
            raise DrawingSourceError(
                f"vvs_engine-artefakter i schema {schema}; "
                f"adaptern stöder {self.config.supported_artifact_schemas}"
            )
        input_sha = str(manifest.get("input_pdf_sha256") or "")
        if expected_sha256 and input_sha != expected_sha256:
            raise DrawingSourceError("vvs_engine-resultatet gäller en annan fil än den som skickades in")
        version = (
            f"vvs_engine {manifest.get('engine_version')} @{str(manifest.get('source_revision', ''))[:7]}"
        )
        coverage = {
            int(sh["page"]): sh
            for sh in _read(out_dir / "reading-coverage.json").get("sheets", [])
            if "page" in sh
        }
        sheets_dir = out_dir / "sheets"
        sheets = [
            self._sheet(sheets_dir / name, coverage, version)
            for name in sorted((p.name for p in sheets_dir.iterdir() if p.is_dir()), key=int)
        ]
        warnings = []
        summary_path = out_dir / "summary.json"
        if summary_path.exists():
            skipped = _read(summary_path).get("skipped_pages") or []
            warnings += [f"vvs_engine hoppade över sida {s}" for s in skipped]
        return DrawingTakeoff(
            source=METHOD, source_version=version, input_sha256=input_sha, sheets=sheets, warnings=warnings
        )

    def _sheet(self, sheet_dir: Path, coverage: dict[int, dict[str, Any]], version: str) -> SheetTakeoff:
        page_info = _read(sheet_dir / "page.json")
        index = int(page_info["page"])  # motorns sidindex är 0-baserat
        page = index + 1
        quantities = _read(sheet_dir / "quantities.json")
        pipes = {p["physical_pipe_id"]: p for p in _read(sheet_dir / "physical-pipes.json")["physical_pipes"]}
        scale = self._scale(page, quantities.get("scale") or {})
        runs = [self._run(page, row, pipes, scale, version) for row in quantities.get("rows", [])]
        symbols = self._risers(page, quantities.get("risers") or {}, version)
        designations = _read(sheet_dir / "vector-designations.json").get("designations", [])
        legend = [
            LegendEntryDraft(
                page=page,
                code=str(e.get("code", "")),
                description=str(e.get("description", "")),
                role=e.get("role"),
                flags=["unreadable_chars"] if "?" in str(e.get("description", "")) else [],
            )
            for e in _read(sheet_dir / "drawing-legend.json").get("entries", [])
        ]
        symbols += self._tags(page, designations, {e.code for e in legend}, version)
        cov = coverage.get(index)
        return SheetTakeoff(
            page=page,
            width_pt=_float(page_info.get("width_pt")),
            height_pt=_float(page_info.get("height_pt")),
            scale=scale,
            coverage=SheetCoverage(
                page=page,
                drawn_m=_float(cov.get("drawn_m")),
                confirmed_m=_float(cov.get("confirmed_m")),
                ambiguous_m=_float(cov.get("ambiguous_m")),
                unowned_m=_float(cov.get("unowned_m")),
            )
            if cov
            else None,
            pipe_runs=runs,
            symbols=symbols,
            legend=legend,
            designations_read=[str(d.get("raw_text") or d.get("text") or "") for d in designations],
        )

    def _scale(self, page: int, scale: dict[str, Any]) -> SheetScale:
        state = str(scale.get("state") or "UNKNOWN")
        return SheetScale(
            page=page,
            state=state,
            verified=state in self.config.verified_scale_states,
            meters_per_pt=_float(scale.get("meters_per_pdf_point") or scale.get("meters_per_pt")),
            reason=scale.get("reason"),
            evidence=list(scale.get("evidence") or []),
        )

    def _member_confidence(self, members: list[dict[str, Any]]) -> tuple[float, list[str]]:
        """Nivåns konfidens, begränsad av vad som namnger röret när det bara är en etikett utan egen ledare
        (h.2, 0,8) eller en ledare fångad strax före röret (h.1, 0,7)."""
        confidence, flags = self._confidence([m.get("confidence_tier") for m in members])
        caps = [float(m["anchor_confidence"]) for m in members if m.get("anchor_confidence") is not None]
        return (min([confidence, *caps]) if caps else confidence), flags

    def _confidence(self, tiers: list[str | None]) -> tuple[float, list[str]]:
        flags: list[str] = []
        values = []
        for tier in tiers:
            if tier in self.config.confidence_tiers:
                values.append(self.config.confidence_tiers[tier])
            else:
                values.append(self.config.unknown_tier_confidence)
                flags.append(f"unknown_confidence_tier:{tier}")
        return (min(values) if values else self.config.unknown_tier_confidence), sorted(set(flags))

    def _run(
        self,
        page: int,
        row: dict[str, Any],
        pipes: dict[str, dict[str, Any]],
        scale: SheetScale,
        version: str,
    ) -> PipeRunDraft:
        designation = str(row.get("designation") or "")
        system, material, dim, parse_flags = _parse_designation(designation)
        if row.get("dn") is not None:
            engine_dim = str(row["dn"])
            if dim is not None and dim.rstrip("L") != engine_dim:
                parse_flags.append(f"dim_disagreement:{dim}!={engine_dim}")
            dim = dim or engine_dim
        pipe_ids = [str(p) for p in row.get("pipe_ids") or []]
        members = [pipes[p] for p in pipe_ids if p in pipes]
        confidence, conf_flags = self._member_confidence(members)
        flags = [*parse_flags, *conf_flags]
        state = str(row.get("state") or "UNKNOWN")
        if state not in self.config.confirmed_states:
            flags.append(f"state:{state}")
            confidence = 0.0
        if not scale.verified:
            flags.append(f"scale_not_verified:{scale.state}")
        if any(m.get("needs_review") for m in members):
            flags.append("needs_review")
        if (row.get("ambiguous_m") or 0) > 0:
            flags.append("has_ambiguous_length")
        vertical = row.get("vertical_m")
        refs = [
            SourceRef(
                page=page,
                bbox=_bbox_of(m.get("geometry") or []),
                method=METHOD,
                model=version,
                confidence=self._member_confidence([m])[0],
                evidence={
                    "physical_pipe_id": m.get("physical_pipe_id"),
                    "identity": m.get("identity"),
                    "evidence_state": m.get("evidence_state"),
                    "evidence": m.get("evidence") or [],
                    "supporting_anchors": m.get("supporting_anchors") or [],
                    "source_path_ids": m.get("source_path_ids") or [],
                    "frontier_reasons": m.get("frontier_reasons") or [],
                    "representation_family": m.get("representation_family"),
                    "confidence_tier": m.get("confidence_tier"),
                },
            )
            for m in members
        ]
        missing = [p for p in pipe_ids if p not in pipes]
        if missing:
            flags.append("pipe_ids_missing_in_artifacts")
        return PipeRunDraft(
            page=page,
            designation=designation,
            system=system or row.get("system"),
            material=material,
            dim=dim,
            length_m_horizontal=float(row.get("confirmed_horizontal_m") or 0.0),
            length_m_vertical=_float(vertical) if row.get("vertical_known") else None,
            length_m_total=_float(row.get("confirmed_total_m")),
            ambiguous_m=float(row.get("ambiguous_m") or 0.0),
            in_hatched_area_m=float(row.get("in_hatched_area_m") or 0.0),
            riser_count=int(row.get("riser_count") or 0),
            state=state,
            confidence=confidence,
            segment_ids=pipe_ids,
            flags=sorted(set(flags)),
            source_refs=refs,
        )

    def _risers(self, page: int, risers: dict[str, list[dict[str, Any]]], version: str) -> list[SymbolDraft]:
        out = []
        for identity, marks in sorted(risers.items()):
            for mark in marks:
                x, y = (mark.get("point") or [None, None])[:2]
                bbox = (x, y, x, y) if isinstance(x, int | float) and isinstance(y, int | float) else None
                out.append(
                    SymbolDraft(
                        page=page,
                        kind="riser",
                        tag=mark.get("designation") or identity,
                        bbox=bbox,
                        read_method=f"{METHOD}:{mark.get('source', 'unknown')}",
                        confidence=self.config.confidence_tiers.get(
                            "inferred", self.config.unknown_tier_confidence
                        ),
                        flags=[],
                        source_refs=[
                            SourceRef(
                                page=page,
                                bbox=bbox,
                                method=METHOD,
                                model=version,
                                evidence={
                                    "identity": identity,
                                    "symbol_path": mark.get("symbol"),
                                    "anchor_id": mark.get("anchor_id"),
                                    "count_prefix": mark.get("count_prefix"),
                                },
                            )
                        ],
                    )
                )
        return out

    def _tags(
        self, page: int, designations: list[dict[str, Any]], legend_codes: set[str], version: str
    ) -> list[SymbolDraft]:
        """Objekttaggar (B201B, AV201-15, RA101) som motorn läst. Det är förekomster av text, inte detekterade
        symboler – SPEC 6.4.3 i kräver att de länkas till en ritad symbol innan de räknas som symboler."""
        pattern = load_label_grammar().object.pattern
        out = []
        for d in designations:
            text = str(d.get("raw_text") or d.get("text") or "")
            if text in legend_codes or not re.match(pattern, text):
                continue  # legendens egna koder (S02, VS21 …) är inga förekomster på ritningen
            bbox_raw = d.get("bbox")
            bbox = (
                tuple(float(v) for v in bbox_raw)
                if isinstance(bbox_raw, list) and len(bbox_raw) == 4
                else None
            )
            glyph_conf = _float(d.get("min_glyph_confidence"))
            out.append(
                SymbolDraft(
                    page=page,
                    kind="tag",
                    tag=text,
                    bbox=bbox,
                    read_method=f"{METHOD}:{d.get('source', 'stroke')}",
                    confidence=min(glyph_conf if glyph_conf is not None else 0.0, 1.0),
                    flags=["text_occurrence_not_symbol"]
                    + (["unknown_chars"] if d.get("unknown_chars") else []),
                    source_refs=[
                        SourceRef(
                            page=page,
                            bbox=bbox,
                            method=METHOD,
                            model=version,
                            confidence=glyph_conf,
                            evidence={"designation_id": d.get("did"), "layer": d.get("layer")},
                        )
                    ],
                )
            )
        return out


def _parse_designation(designation: str) -> tuple[str | None, str | None, str | None, list[str]]:
    """Beteckningen tolkad med VS-Kalkyls grammatik (Bilaga B.4). Okänt = None + flagga, aldrig gissat."""
    m = re.match(load_label_grammar().pipe.pattern, designation)
    if not m:
        return None, None, None, ["designation_unparsed"]
    flags = []
    if m.group("suffixes"):
        flags.append(f"suffix:{m.group('suffixes').lstrip('-')}")
    return m.group("system"), m.group("material"), m.group("dim"), flags


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
