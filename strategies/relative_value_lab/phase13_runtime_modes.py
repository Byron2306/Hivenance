from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


# These are runtime-control organs currently consumed by the hypothesis path.
PHASE13_MODE_CONTROLLED_ORGANS=(
    "strategy_workers",
    "worker_coalition",
    "learning_memory",
    "statistics_bee",
)


@dataclass(frozen=True)
class Phase13ModeSnapshot:
    frozen_modes: Mapping[str,str]
    adaptive_modes: Mapping[str,str]
    frozen_modes_mutable: bool=False
    adaptive_modes_mutable: bool=True
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if self.frozen_modes_mutable:
            raise ValueError("phase13_frozen_modes_must_be_immutable")
        if not self.adaptive_modes_mutable:
            raise ValueError("phase13_adaptive_modes_must_be_mutable")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("phase13_mode_snapshot_authority_escalation_forbidden")


def build_phase13_mode_snapshot(
    *,
    adaptive_control: Mapping[str,Mapping[str,Any]]|None=None,
    controlled_organs: Sequence[str]=PHASE13_MODE_CONTROLLED_ORGANS,
)->Phase13ModeSnapshot:
    adaptive_control=dict(adaptive_control or {})
    frozen={
        str(organ_id):"ACTIVE"
        for organ_id in controlled_organs
    }
    adaptive={}
    for organ_id in controlled_organs:
        row=adaptive_control.get(str(organ_id)) or {}
        adaptive[str(organ_id)]=str(row.get("mode") or "SHADOW").upper()
    return Phase13ModeSnapshot(
        frozen_modes=frozen,
        adaptive_modes=adaptive,
        frozen_modes_mutable=False,
        adaptive_modes_mutable=True,
        execution_eligible=False,
        promotion_eligible=False,
    )
