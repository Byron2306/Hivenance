"""Frozen eight-attack Phase-12 historical prosecution gauntlet."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from .historical_causal_prosecution import (
    ADVERSARIAL_ATTACKS,
)
from .historical_matrix_adversarial import (
    HistoricalAdversarialReceipt,
)


@dataclass(frozen=True)
class HistoricalAdversarialGauntletReceipt:
    schema: str
    attacks: tuple[
        HistoricalAdversarialReceipt,
        ...
    ]

    all_attacks_accounted: bool
    refusal_attacks_passed: bool
    lineage_attacks_passed: bool

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self):
        return asdict(self)


def evaluate_adversarial_gauntlet(
    *,
    attacks: Mapping[
        str,
        HistoricalAdversarialReceipt,
    ],
) -> HistoricalAdversarialGauntletReceipt:

    missing = tuple(
        attack
        for attack in ADVERSARIAL_ATTACKS
        if attack not in attacks
    )

    if missing:
        raise ValueError(
            "historical_adversarial_gauntlet_missing_attacks:"
            + ",".join(missing)
        )

    ordered = tuple(
        attacks[x]
        for x in ADVERSARIAL_ATTACKS
    )

    refusal_required = {
        "DELAY_EVIDENCE",
        "STALE_WORLD_BINDING",
        "ROOT_SUBSTITUTION",
        "TIME_SHIFT_PLACEBO",
    }

    refusal_pass = all(
        attacks[x].detected
        and attacks[x].refused
        for x in refusal_required
    )

    lineage_pass = all(
        attacks[x].detected
        and not attacks[x].refused
        for x in {
            "DUPLICATE_LINEAGE",
            "FALSE_UNISON",
        }
    )

    accounted = all(
        attacks[x].detected
        for x in ADVERSARIAL_ATTACKS
    )

    return HistoricalAdversarialGauntletReceipt(
        schema=(
            "hivenance_historical_adversarial_gauntlet_v1"
        ),
        attacks=ordered,
        all_attacks_accounted=(
            accounted
        ),
        refusal_attacks_passed=(
            refusal_pass
        ),
        lineage_attacks_passed=(
            lineage_pass
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )
