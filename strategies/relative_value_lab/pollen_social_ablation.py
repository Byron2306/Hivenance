from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SocialAblationArm:
    name: str
    pollen_rewards_enabled: bool
    reputation_updates_enabled: bool

    total_rewarded: float
    dissent_reward: float
    support_reward: float

    dissent_reputation_before: float
    dissent_reputation_after: float
    support_reputation_before: float
    support_reputation_after: float

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PollenSocialAblationReceipt:
    schema: str
    receipt_id: str
    hypothesis_id: str
    outcome_id: str

    arms: tuple[SocialAblationArm, ...]

    pollen_reward_effect_observed: bool
    reputation_effect_observed: bool
    pollen_and_reputation_separately_ablatable: bool

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["arms"] = tuple(
            arm.to_dict()
            for arm in self.arms
        )
        return payload


def build_social_ablation_receipt(
    *,
    hypothesis_id: str,
    outcome_id: str,
    arms: tuple[SocialAblationArm, ...],
) -> PollenSocialAblationReceipt:

    by_name: Mapping[str, SocialAblationArm] = {
        arm.name: arm
        for arm in arms
    }

    required = {
        "FULL",
        "NO_POLLEN_REWARD",
        "NO_REPUTATION",
        "NO_POLLEN_OR_REPUTATION",
    }

    if set(by_name) != required:
        raise ValueError(
            "phase9_social_ablation_requires_exact_2x2_arms"
        )

    full = by_name["FULL"]
    no_pollen = by_name["NO_POLLEN_REWARD"]
    no_rep = by_name["NO_REPUTATION"]
    neither = by_name["NO_POLLEN_OR_REPUTATION"]

    pollen_effect = bool(
        full.total_rewarded > 0.0
        and no_pollen.total_rewarded == 0.0
        and no_rep.total_rewarded > 0.0
        and neither.total_rewarded == 0.0
    )

    reputation_effect = bool(
        full.dissent_reputation_after
        != full.dissent_reputation_before
        and no_pollen.dissent_reputation_after
        != no_pollen.dissent_reputation_before
        and no_rep.dissent_reputation_after
        == no_rep.dissent_reputation_before
        and neither.dissent_reputation_after
        == neither.dissent_reputation_before
    )

    separate = bool(
        pollen_effect
        and reputation_effect
        and no_pollen.reputation_updates_enabled
        and no_rep.pollen_rewards_enabled
    )

    body = {
        "hypothesis_id": hypothesis_id,
        "outcome_id": outcome_id,
        "arms": [
            arm.to_dict()
            for arm in sorted(
                arms,
                key=lambda row: row.name,
            )
        ],
    }

    return PollenSocialAblationReceipt(
        schema="hivenance_pollen_social_ablation_v1",
        receipt_id=(
            "psabl_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        hypothesis_id=str(hypothesis_id),
        outcome_id=str(outcome_id),
        arms=tuple(
            sorted(
                arms,
                key=lambda row: row.name,
            )
        ),
        pollen_reward_effect_observed=pollen_effect,
        reputation_effect_observed=reputation_effect,
        pollen_and_reputation_separately_ablatable=separate,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
