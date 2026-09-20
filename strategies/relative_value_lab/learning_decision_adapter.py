from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import RELATIVE_VALUE_AUTHORITY
from .learning_influence_gate import (
    LearningInfluenceDecision,
)


@dataclass(frozen=True)
class LearningAdjustedDecision:
    schema: str

    original_direction: str
    final_direction: str

    original_abstain: bool
    final_abstain: bool

    learning_effect: str
    learning_decision_id: str

    reason: str

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def apply_learning_influence(
    *,
    direction: str,
    abstain: bool,
    learning: LearningInfluenceDecision,
) -> LearningAdjustedDecision:
    """Learning may preserve or reduce a decision, never create one."""

    original_direction = str(
        direction
    ).upper()

    original_abstain = bool(
        abstain
    )

    if learning.veto:
        final_direction = "ABSTAIN"
        final_abstain = True
        reason = (
            "applicable_negative_learning_veto"
        )

    else:
        final_direction = (
            "ABSTAIN"
            if original_abstain
            else original_direction
        )
        final_abstain = original_abstain
        reason = (
            "learning_context_did_not_escalate_decision"
        )

    return LearningAdjustedDecision(
        schema=(
            "hivenance_learning_adjusted_decision_v1"
        ),
        original_direction=original_direction,
        final_direction=final_direction,
        original_abstain=original_abstain,
        final_abstain=final_abstain,
        learning_effect=learning.effect,
        learning_decision_id=(
            learning.decision_id
        ),
        reason=reason,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
