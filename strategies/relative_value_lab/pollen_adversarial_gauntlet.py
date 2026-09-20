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


ATTACKS = (
    "DUPLICATE_LINEAGE_FALSE_UNISON",
    "SAME_ROOT_CLONE_SWARM",
    "DELAYED_RESPONSE",
    "STALE_TESTIMONY",
    "COORDINATED_WRONG_AGREEMENT",
    "USEFUL_DISSENT",
)


@dataclass(frozen=True)
class SocialAttackResult:
    attack: str
    passed: bool
    reason: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.attack not in ATTACKS:
            raise ValueError("unknown_phase9_social_attack")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PollenAdversarialGauntletReceipt:
    schema: str
    receipt_id: str
    hypothesis_id: str

    attacks: tuple[SocialAttackResult, ...]
    passed_attack_count: int
    total_attack_count: int
    all_attacks_passed: bool

    clone_independence_preserved: bool
    delayed_testimony_rejected_as_quorum: bool
    stale_testimony_rejected: bool
    wrong_consensus_denied_truth: bool
    useful_dissent_rewarded: bool

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["attacks"] = tuple(
            row.to_dict()
            for row in self.attacks
        )
        return payload


def build_adversarial_gauntlet_receipt(
    *,
    hypothesis_id: str,
    results: tuple[SocialAttackResult, ...],
) -> PollenAdversarialGauntletReceipt:

    names = tuple(row.attack for row in results)

    if len(names) != len(set(names)):
        raise ValueError("duplicate_phase9_attack_result")

    missing = sorted(set(ATTACKS) - set(names))
    extra = sorted(set(names) - set(ATTACKS))

    if missing:
        raise ValueError(
            "phase9_attack_results_missing:"
            + ",".join(missing)
        )

    if extra:
        raise ValueError(
            "phase9_attack_results_extra:"
            + ",".join(extra)
        )

    by_attack = {
        row.attack: row
        for row in results
    }

    body = {
        "hypothesis_id": hypothesis_id,
        "results": [
            row.to_dict()
            for row in sorted(
                results,
                key=lambda x: x.attack,
            )
        ],
    }

    passed = sum(
        1
        for row in results
        if row.passed
    )

    return PollenAdversarialGauntletReceipt(
        schema=(
            "hivenance_pollen_adversarial_gauntlet_v1"
        ),
        receipt_id=(
            "pgaunt_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        hypothesis_id=str(hypothesis_id),
        attacks=tuple(
            sorted(
                results,
                key=lambda x: x.attack,
            )
        ),
        passed_attack_count=passed,
        total_attack_count=len(ATTACKS),
        all_attacks_passed=(
            passed == len(ATTACKS)
        ),
        clone_independence_preserved=bool(
            by_attack[
                "DUPLICATE_LINEAGE_FALSE_UNISON"
            ].passed
            and by_attack[
                "SAME_ROOT_CLONE_SWARM"
            ].passed
        ),
        delayed_testimony_rejected_as_quorum=bool(
            by_attack["DELAYED_RESPONSE"].passed
        ),
        stale_testimony_rejected=bool(
            by_attack["STALE_TESTIMONY"].passed
        ),
        wrong_consensus_denied_truth=bool(
            by_attack[
                "COORDINATED_WRONG_AGREEMENT"
            ].passed
        ),
        useful_dissent_rewarded=bool(
            by_attack["USEFUL_DISSENT"].passed
        ),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
