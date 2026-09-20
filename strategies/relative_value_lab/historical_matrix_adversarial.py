"""Phase-12 adversarial attacks against historical causal prosecution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .historical_causal_prosecution import (
    ADVERSARIAL_ATTACKS,
)
from .hypothesis_envelope import (
    CanonicalHypothesisEnvelope,
)


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return "sha256:" + hashlib.sha256(
        raw
    ).hexdigest()


@dataclass(frozen=True)
class HistoricalAdversarialReceipt:
    schema: str
    receipt_id: str

    attack_id: str
    detected: bool
    refused: bool

    reason: str

    full_envelope_id: str
    attacked_envelope_id: str | None

    full_root_count: int
    attacked_root_count: int

    full_independent_lineage_count: int
    attacked_independent_lineage_count: int

    historical_only: bool = True
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.attack_id not in ADVERSARIAL_ATTACKS:
            raise ValueError(
                "unknown_historical_adversarial_attack"
            )

        if not self.historical_only:
            raise ValueError(
                "historical_attack_must_remain_historical"
            )

        if self.execution_eligible:
            raise ValueError(
                "historical_attack_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "historical_attack_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _walk(value: Any):
    if hasattr(value, "to_dict"):
        value = value.to_dict()

    if isinstance(value, Mapping):
        yield value

        for child in value.values():
            yield from _walk(child)

    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from _walk(child)


def evidence_roots(
    envelope: CanonicalHypothesisEnvelope,
) -> tuple[str, ...]:
    roots = set()

    for node in _walk(
        envelope.sections
    ):
        root = node.get(
            "evidence_root"
        )

        if (
            isinstance(root, str)
            and root.startswith("sha256:")
        ):
            roots.add(root)

        many = node.get(
            "evidence_roots"
        )

        if isinstance(
            many,
            (tuple, list),
        ):
            for item in many:
                if (
                    isinstance(item, str)
                    and item.startswith(
                        "sha256:"
                    )
                ):
                    roots.add(item)

    return tuple(
        sorted(roots)
    )


def independent_lineages(
    envelope: CanonicalHypothesisEnvelope,
) -> tuple[str, ...]:
    lineages = set()

    for node in _walk(
        envelope.sections
    ):
        value = node.get(
            "root_lineage_digest"
        )

        if value:
            lineages.add(
                str(value)
            )

    return tuple(
        sorted(lineages)
    )


def _timestamps_after_decision(
    envelope: CanonicalHypothesisEnvelope,
) -> tuple[str, ...]:
    decision_ts = int(
        envelope.conclusion.timestamp_ms
    )

    violations = []

    for node in _walk(
        envelope.sections
    ):
        for key in (
            "observed_at_ms",
            "available_at_ms",
            "created_at_ms",
            "submitted_at_ms",
        ):
            value = node.get(key)

            if value is None:
                continue

            try:
                ts = int(value)
            except (TypeError, ValueError):
                continue

            if ts > decision_ts:
                violations.append(
                    f"{key}:{ts}"
                )

    return tuple(
        sorted(violations)
    )


def attack_guard(
    *,
    attack_id: str,
    full: CanonicalHypothesisEnvelope,
    attacked: CanonicalHypothesisEnvelope | None,
    required_voice: str | None = None,
) -> HistoricalAdversarialReceipt:
    attack_id = str(
        attack_id
    ).upper()

    if attack_id not in ADVERSARIAL_ATTACKS:
        raise ValueError(
            "unknown_historical_adversarial_attack"
        )

    full_roots = evidence_roots(
        full
    )

    full_lineages = independent_lineages(
        full
    )

    attacked_roots = (
        ()
        if attacked is None
        else evidence_roots(attacked)
    )

    attacked_lineages = (
        ()
        if attacked is None
        else independent_lineages(
            attacked
        )
    )

    detected = False
    refused = False
    reason = "NO_ATTACK_EFFECT_DETECTED"

    if attack_id == "STALE_WORLD_BINDING":
        detected = bool(
            attacked is None
            or attacked.world_state_id
            != full.world_state_id
            or attacked.world_state_hash
            != full.world_state_hash
        )

        refused = detected

        reason = (
            "STALE_OR_CROSS_WORLD_BINDING"
            if detected
            else "WORLD_BINDING_UNCHANGED"
        )

    elif attack_id == "ROOT_SUBSTITUTION":
        detected = bool(
            attacked is None
            or set(attacked_roots)
            != set(full_roots)
        )

        refused = detected

        reason = (
            "OBSERVED_ROOT_SET_CHANGED"
            if detected
            else "ROOT_SET_UNCHANGED"
        )

    elif attack_id in {
        "DUPLICATE_LINEAGE",
        "FALSE_UNISON",
    }:
        # Independent lineage count may never increase merely because the
        # same lineage is duplicated or expressed through another transform.
        detected = (
            len(attacked_lineages)
            <= len(full_lineages)
        )

        refused = False

        reason = (
            "DUPLICATE_LINEAGE_DID_NOT_CREATE_INDEPENDENCE"
            if detected
            else "FALSE_INDEPENDENCE_INCREASE"
        )

    elif attack_id == "DELAY_EVIDENCE":
        late = (
            ()
            if attacked is None
            else _timestamps_after_decision(
                attacked
            )
        )

        detected = bool(late)
        refused = detected

        reason = (
            "POST_DECISION_EVIDENCE_DETECTED"
            if detected
            else "NO_DELAY_VIOLATION_FOUND"
        )

    elif attack_id == "TIME_SHIFT_PLACEBO":
        detected = bool(
            attacked is None
            or attacked.conclusion.timestamp_ms
            != full.conclusion.timestamp_ms
            or attacked.conclusion.horizon_seconds
            != full.conclusion.horizon_seconds
        )

        refused = detected

        reason = (
            "TIME_SHIFTED_COUNTERFACTUAL"
            if detected
            else "NO_TIME_SHIFT_FOUND"
        )

    elif attack_id == "MISSING_VOICE":
        if required_voice is None:
            raise ValueError(
                "missing_voice_attack_requires_voice"
            )

        family = str(
            required_voice
        ).upper()

        full_has = _contains_family(
            full,
            family,
        )

        attacked_has = (
            False
            if attacked is None
            else _contains_family(
                attacked,
                family,
            )
        )

        detected = (
            full_has
            and not attacked_has
        )

        refused = False

        reason = (
            "VOICE_EXPLICITLY_MISSING"
            if detected
            else "VOICE_NOT_REMOVED"
        )

    elif attack_id == "SHUFFLE_EVIDENCE":
        if attacked is None:
            detected = True
            refused = True
            reason = "SHUFFLE_ATTACK_MISSING_ENVELOPE"

        else:
            same_roots = (
                set(attacked_roots)
                == set(full_roots)
            )

            def causal_conclusion_surface(envelope):
                c = envelope.conclusion

                return {
                    "symbol": c.symbol,
                    "timestamp_ms": c.timestamp_ms,
                    "horizon_seconds": c.horizon_seconds,
                    "direction": c.direction,
                    "abstain": c.abstain,
                    "expected_move_bps": c.expected_move_bps,
                    "expected_cost_bps": c.expected_cost_bps,
                    "expected_net_bps": c.expected_net_bps,
                    "uncertainty": c.uncertainty,
                    "influence_ids": tuple(
                        c.influence_ids
                    ),
                }

            same_conclusion = (
                causal_conclusion_surface(
                    attacked
                )
                == causal_conclusion_surface(
                    full
                )
            )

            detected = bool(
                same_roots
                and same_conclusion
            )

            refused = False

            reason = (
                "ORDER_ONLY_CHANGE_NO_CAUSAL_EFFECT"
                if detected
                else "SHUFFLE_CHANGED_CAUSAL_STATE"
            )

    body = {
        "attack_id": attack_id,
        "detected": detected,
        "refused": refused,
        "reason": reason,
        "full": full.envelope_id,
        "attacked": (
            attacked.envelope_id
            if attacked is not None
            else None
        ),
        "full_roots": full_roots,
        "attacked_roots":
            attacked_roots,
        "full_lineages":
            full_lineages,
        "attacked_lineages":
            attacked_lineages,
    }

    return HistoricalAdversarialReceipt(
        schema=(
            "hivenance_historical_matrix_adversarial_v1"
        ),
        receipt_id=(
            "hadv_"
            + _digest(body).split(
                ":",
                1,
            )[1][:24]
        ),
        attack_id=attack_id,
        detected=detected,
        refused=refused,
        reason=reason,
        full_envelope_id=(
            full.envelope_id
        ),
        attacked_envelope_id=(
            None
            if attacked is None
            else attacked.envelope_id
        ),
        full_root_count=len(
            full_roots
        ),
        attacked_root_count=len(
            attacked_roots
        ),
        full_independent_lineage_count=len(
            full_lineages
        ),
        attacked_independent_lineage_count=len(
            attacked_lineages
        ),
        historical_only=True,
        execution_eligible=False,
        promotion_eligible=False,
    )


def _contains_family(
    envelope: CanonicalHypothesisEnvelope,
    family: str,
) -> bool:
    target = str(
        family
    ).upper()

    for node in _walk(
        envelope.sections
    ):
        value = node.get(
            "family"
        )

        if (
            value is not None
            and str(value).upper()
            == target
        ):
            return True

    return False
