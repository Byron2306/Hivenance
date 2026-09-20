from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .contracts import RELATIVE_VALUE_AUTHORITY
from .learning_retrieval import ApplicabilityLearningBrief


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class LearningInfluenceDecision:
    schema: str
    decision_id: str

    effect: str
    veto: bool
    challenge: bool

    applicable_learning_ids: tuple[str, ...]
    supporting_learning_ids: tuple[str, ...]
    contradicting_learning_ids: tuple[str, ...]

    reasons: tuple[str, ...]

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.effect not in {
            "CONTEXT_ONLY",
            "CHALLENGE",
            "VETO",
        }:
            raise ValueError(
                "unknown_learning_influence_effect"
            )

        if self.execution_eligible:
            raise ValueError(
                "learning_influence_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "learning_influence_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_learning_influence(
    *,
    brief: ApplicabilityLearningBrief,
    veto_on_contradiction: bool = True,
) -> LearningInfluenceDecision:
    """Convert applicability-safe learning into bounded research influence."""

    supporting = tuple(
        brief.supported_learning_ids
        + brief.regime_dependent_learning_ids
    )

    contradicting = tuple(
        brief.contradicted_learning_ids
    )

    reasons: list[str] = []

    if contradicting and veto_on_contradiction:
        effect = "VETO"
        veto = True
        challenge = True
        reasons.append(
            "applicable_negative_learning_veto"
        )

    elif contradicting:
        effect = "CHALLENGE"
        veto = False
        challenge = True
        reasons.append(
            "applicable_negative_learning_challenge"
        )

    else:
        effect = "CONTEXT_ONLY"
        veto = False
        challenge = False

        if supporting:
            reasons.append(
                "positive_learning_context_only"
            )
        else:
            reasons.append(
                "no_applicable_learning_influence"
            )

    body = {
        "effect": effect,
        "veto": veto,
        "challenge": challenge,
        "applicable_learning_ids":
            brief.applicable_learning_ids,
        "supporting_learning_ids":
            supporting,
        "contradicting_learning_ids":
            contradicting,
        "reasons": reasons,
    }

    return LearningInfluenceDecision(
        schema=(
            "hivenance_learning_influence_decision_v1"
        ),
        decision_id=(
            "linf_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        effect=effect,
        veto=veto,
        challenge=challenge,
        applicable_learning_ids=(
            brief.applicable_learning_ids
        ),
        supporting_learning_ids=(
            supporting
        ),
        contradicting_learning_ids=(
            contradicting
        ),
        reasons=tuple(reasons),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
