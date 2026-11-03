"""Avvikelseregler och deras allvarlighetsgrad (SPEC 6.5). Regelmotorn byggs ut i fas 3; id och grad är
fastlagda här så att alla steg använder samma."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["info", "warning", "critical"]

SEVERITY: dict[str, Severity] = {
    "TB_MENTIONED_NOT_ITEMIZED": "critical",
    "TB_SELF_CONTRADICTION": "warning",
    "TB_QTY_VS_DRAWING": "warning",
    "DRAWING_ITEM_NOT_IN_TB": "critical",
    "MATERIAL_CODE_MISMATCH": "warning",
    "UNKNOWN_LABEL_TOKEN": "warning",
    "SCALE_DISAGREEMENT": "critical",
    "UNASSIGNED_PIPE": "critical",
    "ACCESSORY_NOT_CONFIRMED": "warning",
    "OPTION_REQUIRED": "info",
    "UNDEFINED_VALUE": "warning",
    "CONFLICTING_REQUIREMENTS": "warning",
    "DRAWING_LIST_MISMATCH": "critical",
    "TITLEBLOCK_MISMATCH": "info",
    "DECIDE_WITH_CLIENT": "info",
    "MATERIAL_UNRESOLVED": "warning",
}


@dataclass(frozen=True)
class DeviationDraft:
    rule_id: str
    message: str
    refs: list[dict[str, Any]] = field(default_factory=list)
    question: str | None = None  # föreslagen fråga till konsult/beställare
    severity: Severity | None = None  # None = regelns standardgrad

    @property
    def effective_severity(self) -> Severity:
        return self.severity or SEVERITY[self.rule_id]
