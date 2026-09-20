from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .organ_topology import topology_by_id


ORGAN_MODES = (
    "DORMANT",
    "SHADOW",
    "ADVISORY",
    "ACTIVE",
    "QUARANTINED",
)

INFLUENCE_MODES = {"ADVISORY", "ACTIVE"}
NON_INFLUENCE_MODES = {"DORMANT", "SHADOW", "QUARANTINED"}


@dataclass(frozen=True)
class OrganRuntimeState:
    organ_id: str
    mode: str
    requested_mode: str
    reason: str
    evidence_state: str
    historical_delta_bps: float | None = None
    independent_worlds: int = 0
    prospective_worlds: int = 0
    prospective_positive_worlds: int = 0
    prospective_negative_worlds: int = 0
    influence_enabled: bool = False
    shadow_probe_enabled: bool = True
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.mode not in ORGAN_MODES:
            raise ValueError("unknown_organ_runtime_mode:" + str(self.mode))
        if self.requested_mode not in ORGAN_MODES:
            raise ValueError("unknown_requested_organ_runtime_mode:" + str(self.requested_mode))
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("organ_runtime_authority_escalation_forbidden")
        if self.mode in NON_INFLUENCE_MODES and self.influence_enabled:
            raise ValueError("non_influence_mode_cannot_enable_influence")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_mode_for_evidence(
    *,
    utility_state: str,
    organ_id: str,
) -> tuple[str, str]:
    """Map current evidence to a reversible research mode.

    This is a default recommendation, never a permanent lock. Runtime/operator
    policy may request another research mode. Execution and promotion remain
    independently forbidden here.
    """
    topology = topology_by_id().get(str(organ_id))
    layer = str(topology.layer if topology else "")

    if utility_state == "HISTORICALLY_USEFUL":
        return "SHADOW", "historically_useful_requires_prospective_confirmation"

    if utility_state in {"HISTORICALLY_MIXED", "HISTORICALLY_HARMFUL"}:
        return "QUARANTINED", "mixed_or_harmful_kept_shadow_probe_for_rehabilitation"

    if utility_state == "INFLUENTIAL_UNDERPOWERED":
        return "SHADOW", "underpowered_requires_more_independent_worlds"

    if utility_state == "INERT_ON_TESTED_WORLDS":
        if layer in {"GOVERNANCE", "FALSIFICATION", "META_COGNITION", "TRANSPORT_HEALTH"}:
            return "ADVISORY", "non_alpha_role_retained_despite_decision_inertness"
        return "DORMANT", "decision_inert_but_periodic_shadow_probe_allowed"

    if utility_state in {"UNAVAILABLE", "AVAILABLE_NOT_INVOKED"}:
        return "SHADOW", "unmeasured_or_uninvoked_needs_observation"

    if utility_state == "HISTORICALLY_NEUTRAL":
        return "SHADOW", "neutral_requires_more_evidence"

    return "SHADOW", "evidence_unresolved"


def resolve_runtime_state(
    *,
    organ_id: str,
    utility_state: str,
    requested_mode: str | None = None,
    historical_delta_bps: float | None = None,
    independent_worlds: int = 0,
    prospective_worlds: int = 0,
    prospective_positive_worlds: int = 0,
    prospective_negative_worlds: int = 0,
    minimum_prospective_worlds_for_active: int = 20,
) -> OrganRuntimeState:
    default_mode, default_reason = default_mode_for_evidence(
        utility_state=str(utility_state),
        organ_id=str(organ_id),
    )
    requested = str(requested_mode or default_mode).upper()
    if requested not in ORGAN_MODES:
        raise ValueError("unknown_requested_organ_runtime_mode:" + requested)

    effective = requested
    reason = "runtime_requested_mode"

    # ACTIVE research influence must be prospectively earned. A request may wake
    # any organ, but insufficient evidence degrades ACTIVE to SHADOW rather than
    # creating a permanent hard lock.
    if requested == "ACTIVE":
        enough = int(prospective_worlds) >= int(minimum_prospective_worlds_for_active)
        signs_positive = (
            int(prospective_positive_worlds) > 0
            and int(prospective_negative_worlds) == 0
        )
        if not (enough and signs_positive):
            effective = "SHADOW"
            reason = "active_request_degraded_pending_prospective_evidence"

    # QUARANTINED organs remain alive in shadow probes and can rehabilitate.
    shadow_probe = effective != "ACTIVE" or requested == "QUARANTINED"
    influence = effective in INFLUENCE_MODES

    return OrganRuntimeState(
        organ_id=str(organ_id),
        mode=effective,
        requested_mode=requested,
        reason=reason if requested_mode is not None else default_reason,
        evidence_state=str(utility_state),
        historical_delta_bps=(
            None if historical_delta_bps is None else float(historical_delta_bps)
        ),
        independent_worlds=int(independent_worlds),
        prospective_worlds=int(prospective_worlds),
        prospective_positive_worlds=int(prospective_positive_worlds),
        prospective_negative_worlds=int(prospective_negative_worlds),
        influence_enabled=bool(influence),
        shadow_probe_enabled=bool(shadow_probe),
        execution_eligible=False,
        promotion_eligible=False,
    )


def build_runtime_control_plane(
    utility_rows: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    *,
    requested_modes: Mapping[str, str] | None = None,
    prospective_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    minimum_prospective_worlds_for_active: int = 20,
) -> dict[str, OrganRuntimeState]:
    requested_modes = dict(requested_modes or {})
    prospective_evidence = dict(prospective_evidence or {})
    out: dict[str, OrganRuntimeState] = {}

    for row in utility_rows:
        organ_id = str(row.get("organ_id") or "")
        if not organ_id:
            continue
        prospective = dict(prospective_evidence.get(organ_id) or {})
        out[organ_id] = resolve_runtime_state(
            organ_id=organ_id,
            utility_state=str(row.get("utility_state") or row.get("availability_state") or "UNAVAILABLE"),
            requested_mode=requested_modes.get(organ_id),
            historical_delta_bps=row.get("historical_paired_delta_bps"),
            independent_worlds=int(row.get("dependence_adjusted_world_count") or 0),
            prospective_worlds=int(prospective.get("worlds") or 0),
            prospective_positive_worlds=int(prospective.get("positive_worlds") or 0),
            prospective_negative_worlds=int(prospective.get("negative_worlds") or 0),
            minimum_prospective_worlds_for_active=int(minimum_prospective_worlds_for_active),
        )
    return out
