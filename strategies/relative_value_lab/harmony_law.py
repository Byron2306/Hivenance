from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


MESSAGE_TYPES = {
    "WAGGLE",
    "FOLLOW",
    "DISSENT",
    "SEARCH",
    "ABANDON",
    "ALARM",
    "SETTLE",
}
PULSE_TYPES = {
    "SEARCH_PULSE",
    "DISCOVERY_PULSE",
    "ALARM_PULSE",
    "FREEZE_PULSE",
    "CLEAR_PULSE",
}
NEGATIVE_AUTHORITY_PULSES = {"ALARM_PULSE", "FREEZE_PULSE"}


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def horizon_band(horizon_seconds: Optional[int]) -> str:
    if horizon_seconds is None:
        return "atemporal"
    if horizon_seconds <= 10:
        return "micro"
    if horizon_seconds <= 60:
        return "meso"
    return "macro"


@dataclass(frozen=True)
class HarmonyBeeMessage:
    """Typed testimony emitted by one HiveNance evidence lineage.

    A bee message is cognition, not authority.  The law validator may admit it
    to a choir, refuse it, or strip an invalid claim of independence.  It can
    never create execution or promotion authority.
    """

    message_id: str
    bee_id: str
    family: str
    lineage_digest: str
    message_type: str
    scope: str
    hypothesis_id: str
    world_state_id: str
    world_state_hash: str
    observed_at_ms: int
    evidence_root: str
    horizon_seconds: Optional[int] = None
    direction: str = "ABSTAIN"
    expected_move_bps: Optional[float] = None
    uncertainty: Optional[float] = None
    independent_claimed: bool = False
    control: bool = False
    pulse_type: Optional[str] = None
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarmonyLawDecision:
    schema: str
    decision_id: str
    message_id: str
    accepted: bool
    choir_eligible: bool
    independent_vote_eligible: bool
    horizon_band: str
    authority_effect: str
    violations: tuple[str, ...]
    warnings: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarmonyChorusDecision:
    schema: str
    decision_id: str
    hypothesis_id: str
    accepted_message_ids: tuple[str, ...]
    refused_message_ids: tuple[str, ...]
    independent_lineages: tuple[str, ...]
    dissent_message_ids: tuple[str, ...]
    bands_present: tuple[str, ...]
    cross_horizon_direction_allowed: bool
    authority_effect: str
    violations: tuple[str, ...]
    warnings: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarmonyLawConfig:
    max_world_state_age_ms: int = 15_000
    future_clock_tolerance_ms: int = 1_000
    require_evidence_root: bool = True
    require_registered_independence: bool = True


class HarmonyLaw:
    """Deterministic constitutional law for HiveNance bee testimony.

    Laws enforced:
      1. One bounded world state.
      2. One independent vote per registered lineage.
      3. Horizons remain polyphonic and may not be collapsed into one direction.
      4. Dissent remains visible.
      5. Resonance/testimony cannot create authority.
      6. Positive pulses can increase attention only; alarm/freeze may reduce it.
      7. Stale, unbound or malformed testimony fails closed.
    """

    version = "hivenance.harmony_law.v1"

    def __init__(
        self,
        *,
        registered_lineages: Mapping[str, str] | None = None,
        config: HarmonyLawConfig | None = None,
    ) -> None:
        # lineage_digest -> canonical family
        self.registered_lineages = dict(registered_lineages or {})
        self.config = config or HarmonyLawConfig()

    def validate_message(
        self,
        message: HarmonyBeeMessage,
        *,
        current_world_state_id: str,
        current_world_state_hash: str,
        now_ms: int,
    ) -> HarmonyLawDecision:
        violations: list[str] = []
        warnings: list[str] = []

        if message.message_type not in MESSAGE_TYPES:
            violations.append("unknown_message_type")
        if message.pulse_type is not None and message.pulse_type not in PULSE_TYPES:
            violations.append("unknown_pulse_type")

        if message.authority != RELATIVE_VALUE_AUTHORITY:
            violations.append("authority_mismatch")
        if message.execution_eligible:
            violations.append("execution_authority_forbidden")
        if message.promotion_eligible:
            violations.append("promotion_authority_forbidden")

        if not message.world_state_id or not message.world_state_hash:
            violations.append("world_state_binding_missing")
        elif (
            message.world_state_id != current_world_state_id
            or message.world_state_hash != current_world_state_hash
        ):
            violations.append("world_state_drift")

        age_ms = int(now_ms) - int(message.observed_at_ms)
        if age_ms > int(self.config.max_world_state_age_ms):
            violations.append("stale_world_state")
        if age_ms < -int(self.config.future_clock_tolerance_ms):
            violations.append("future_timestamp_outside_tolerance")

        if self.config.require_evidence_root and not str(message.evidence_root or "").startswith("sha256:"):
            violations.append("evidence_root_missing_or_unbound")

        canonical_family = self.registered_lineages.get(message.lineage_digest)
        registered = canonical_family is not None
        family_matches = registered and canonical_family == message.family

        independent = bool(
            message.independent_claimed
            and not message.control
            and registered
            and family_matches
        )
        if message.independent_claimed and self.config.require_registered_independence:
            if not registered:
                warnings.append("independence_stripped_unregistered_lineage")
            elif not family_matches:
                violations.append("registered_lineage_family_mismatch")
        if message.control and message.independent_claimed:
            warnings.append("control_cannot_vote_independently")

        # Dissent and alarm testimony stays admissible if otherwise valid.  The
        # law does not silence uncomfortable evidence.
        if message.message_type == "DISSENT":
            warnings.append("dissent_must_be_preserved")

        authority_effect = "NONE"
        if message.pulse_type in NEGATIVE_AUTHORITY_PULSES:
            authority_effect = "REDUCE_OR_FREEZE_ONLY"
        elif message.pulse_type in {"SEARCH_PULSE", "DISCOVERY_PULSE", "CLEAR_PULSE"}:
            authority_effect = "ATTENTION_ONLY"

        accepted = not violations
        body = {
            "message_id": message.message_id,
            "accepted": accepted,
            "independent": independent,
            "violations": sorted(set(violations)),
            "warnings": sorted(set(warnings)),
            "authority_effect": authority_effect,
        }
        return HarmonyLawDecision(
            schema="hivenance_harmony_law_decision_v1",
            decision_id="hld_" + _digest(body).split(":", 1)[1][:24],
            message_id=message.message_id,
            accepted=accepted,
            choir_eligible=accepted,
            independent_vote_eligible=accepted and independent,
            horizon_band=horizon_band(message.horizon_seconds),
            authority_effect=authority_effect,
            violations=tuple(sorted(set(violations))),
            warnings=tuple(sorted(set(warnings))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def validate_chorus(
        self,
        messages: Sequence[HarmonyBeeMessage],
        *,
        current_world_state_id: str,
        current_world_state_hash: str,
        now_ms: int,
        requested_global_direction: bool = False,
    ) -> HarmonyChorusDecision:
        if not messages:
            body = {"empty": True}
            return HarmonyChorusDecision(
                schema="hivenance_harmony_chorus_decision_v1",
                decision_id="hcd_" + _digest(body).split(":", 1)[1][:24],
                hypothesis_id="",
                accepted_message_ids=(),
                refused_message_ids=(),
                independent_lineages=(),
                dissent_message_ids=(),
                bands_present=(),
                cross_horizon_direction_allowed=False,
                authority_effect="NONE",
                violations=("empty_chorus",),
                warnings=(),
            )

        hypotheses = {m.hypothesis_id for m in messages}
        violations: list[str] = []
        warnings: list[str] = []
        if len(hypotheses) != 1:
            violations.append("mixed_hypotheses_in_one_chorus")

        decisions = [
            self.validate_message(
                m,
                current_world_state_id=current_world_state_id,
                current_world_state_hash=current_world_state_hash,
                now_ms=now_ms,
            )
            for m in messages
        ]

        accepted_ids = [d.message_id for d in decisions if d.accepted]
        refused_ids = [d.message_id for d in decisions if not d.accepted]
        bands = sorted({d.horizon_band for d in decisions if d.accepted})

        # One vote per lineage per horizon band. Duplicate descendants may still
        # remain visible as testimony but cannot manufacture quorum.
        lineage_band_seen: set[tuple[str, str]] = set()
        independent_lineages: set[str] = set()
        for message, decision in zip(messages, decisions):
            if not decision.independent_vote_eligible:
                continue
            key = (message.lineage_digest, decision.horizon_band)
            if key in lineage_band_seen:
                warnings.append("clone_vote_collapsed")
                continue
            lineage_band_seen.add(key)
            independent_lineages.add(message.lineage_digest)

        if requested_global_direction and len(set(bands) - {"atemporal"}) > 1:
            violations.append("cross_horizon_direction_collapse_forbidden")

        dissent_ids = [
            message.message_id
            for message, decision in zip(messages, decisions)
            if decision.accepted and message.message_type == "DISSENT"
        ]
        if dissent_ids:
            warnings.append("dissent_preserved")

        authority_effects = {d.authority_effect for d in decisions}
        if "REDUCE_OR_FREEZE_ONLY" in authority_effects:
            authority_effect = "REDUCE_OR_FREEZE_ONLY"
        elif "ATTENTION_ONLY" in authority_effects:
            authority_effect = "ATTENTION_ONLY"
        else:
            authority_effect = "NONE"

        # A chorus can never bootstrap execution/promotion authority.
        if any(m.execution_eligible or m.promotion_eligible for m in messages):
            violations.append("chorus_authority_bootstrap_forbidden")

        body = {
            "hypotheses": sorted(hypotheses),
            "accepted": accepted_ids,
            "refused": refused_ids,
            "lineages": sorted(independent_lineages),
            "dissent": dissent_ids,
            "bands": bands,
            "violations": sorted(set(violations)),
            "warnings": sorted(set(warnings)),
        }
        return HarmonyChorusDecision(
            schema="hivenance_harmony_chorus_decision_v1",
            decision_id="hcd_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=next(iter(hypotheses)) if len(hypotheses) == 1 else "",
            accepted_message_ids=tuple(accepted_ids),
            refused_message_ids=tuple(refused_ids),
            independent_lineages=tuple(sorted(independent_lineages)),
            dissent_message_ids=tuple(dissent_ids),
            bands_present=tuple(bands),
            cross_horizon_direction_allowed=False,
            authority_effect=authority_effect,
            violations=tuple(sorted(set(violations))),
            warnings=tuple(sorted(set(warnings))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )


def make_message_id(payload: Mapping[str, Any]) -> str:
    return "bee_" + _digest(dict(payload)).split(":", 1)[1][:24]
