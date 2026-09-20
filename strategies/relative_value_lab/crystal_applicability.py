from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .contracts import RELATIVE_VALUE_AUTHORITY
from .learning_applicability import (
    ApplicabilityDecision,
    LiveResearchContext,
    applicability_from_receipt,
    evaluate_learning_applicability,
)


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


CRYSTAL_KINDS = {
    "POSITIVE_THESIS",
    "NEGATIVE_CAPABILITY",
}


@dataclass(frozen=True)
class CrystalApplicabilityDecision:
    schema: str
    decision_id: str

    crystal_id: str
    crystal_kind: str

    applicable: bool
    effect: str

    applicability: ApplicabilityDecision

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.crystal_kind not in CRYSTAL_KINDS:
            raise ValueError(
                "unknown_crystal_kind"
            )

        if self.effect not in {
            "CONTEXT_ONLY",
            "VETO_ELIGIBLE",
            "NO_INFLUENCE",
        }:
            raise ValueError(
                "unknown_crystal_effect"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_crystal_applicability(
    *,
    crystal: Mapping[str, Any],
    context: LiveResearchContext,
    max_age_ms: int | None = None,
) -> CrystalApplicabilityDecision:

    crystal_id = str(
        crystal.get("crystal_id")
        or crystal.get("learning_id")
        or ""
    )

    if not crystal_id:
        raise ValueError(
            "crystal_id_required"
        )

    crystal_kind = str(
        crystal.get("crystal_kind")
        or crystal.get("kind")
        or ""
    ).upper()

    if crystal_kind not in CRYSTAL_KINDS:
        raise ValueError(
            "unknown_crystal_kind"
        )

    declared_state = (
        "CONTRADICTED"
        if crystal_kind == "NEGATIVE_CAPABILITY"
        else "SUPPORTED"
    )

    applicability = evaluate_learning_applicability(
        learning_id=crystal_id,
        applicability=applicability_from_receipt(
            crystal
        ),
        context=context,
        max_age_ms=max_age_ms,
        superseded=bool(
            crystal.get("superseded", False)
            or crystal.get("superseded_by")
        ),
        declared_state=declared_state,
    )

    if not applicability.applicable:
        effect = "NO_INFLUENCE"

    elif crystal_kind == "NEGATIVE_CAPABILITY":
        effect = "VETO_ELIGIBLE"

    else:
        effect = "CONTEXT_ONLY"

    body = {
        "crystal_id": crystal_id,
        "crystal_kind": crystal_kind,
        "applicability_decision_id":
            applicability.decision_id,
        "effect": effect,
    }

    return CrystalApplicabilityDecision(
        schema=(
            "hivenance_crystal_applicability_decision_v1"
        ),
        decision_id=(
            "capp_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        crystal_id=crystal_id,
        crystal_kind=crystal_kind,
        applicable=applicability.applicable,
        effect=effect,
        applicability=applicability,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
