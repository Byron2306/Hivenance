from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .research_context import ResearchContext


@dataclass(frozen=True)
class OrganContextView:
    organ_id: str
    context_id: str
    world_state_id: str
    world_state_hash: str
    as_of_ms: int
    sections: Mapping[str, Any]
    allowed_sections: tuple[str, ...]
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("organ_context_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sections"] = dict(self.sections)
        return payload


_ALLOWED = {
    "strategy_workers": ("observed", "regime", "statistics", "learning", "crystals", "calibration"),
    "hypothesis_competition": ("observed", "regime", "statistics", "learning", "crystals", "external", "calibration"),
    "coin_selector": ("observed", "regime", "statistics", "external"),
    "ml_challenger": ("observed", "regime", "statistics", "learning", "external", "calibration"),
    "market_hunting": ("observed", "regime", "statistics", "external", "provenance"),
    "colony_correlation": ("observed", "provenance"),
    "causal_cascade": ("observed", "provenance"),
    "mystique": ("observed", "regime", "statistics", "learning", "provenance"),
    "polyphonic_quorum": ("provenance",),
    "pollen_economy": ("learning", "calibration", "workers", "provenance"),
    "cognitive_metabolism": ("calibration", "provenance"),
    "vns_temporal_texture": ("observed", "provenance"),
    "recursive_queen": ("regime", "statistics", "learning", "external", "calibration", "provenance"),
    "conducting_queen": (
        "observed", "regime", "statistics", "learning", "crystals",
        "external", "calibration", "workers", "provenance",
    ),
}


def allowed_sections(organ_id: str) -> tuple[str, ...]:
    return tuple(_ALLOWED.get(str(organ_id), ()))


def project_research_context(
    context: ResearchContext | Mapping[str, Any],
    *,
    organ_id: str,
) -> OrganContextView:
    payload = context.to_dict() if hasattr(context, "to_dict") else dict(context)
    allowed = allowed_sections(organ_id)
    sections = {
        section: payload.get(section, {})
        for section in allowed
    }
    return OrganContextView(
        organ_id=str(organ_id),
        context_id=str(payload.get("context_id") or ""),
        world_state_id=str(payload.get("world_state_id") or ""),
        world_state_hash=str(payload.get("world_state_hash") or ""),
        as_of_ms=int(payload.get("as_of_ms") or 0),
        sections=sections,
        allowed_sections=allowed,
    )
