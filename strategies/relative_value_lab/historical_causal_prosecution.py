"""Phase 12 full-organism historical causal prosecution contracts.

This layer defines the frozen mask roster, paired historical result shape and
survivor classification. It does not manufacture historical utility and does
not convert historical results into prospective authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


PAIRED_MASKS = (
    "FULL_HIVE",
    "NO_LONG_HORIZON_LATTICE",
    "NO_CEX_ORACLE",
    "NO_COMPARISON",
    "NO_COIN_SELECTOR",
    "NO_REGIME",
    "NO_FLOW",
    "NO_LIQUIDITY",
    "NO_VOLATILITY",
    "NO_CROSS_MARKET",
    "NO_TEMPORAL_PARTICIPATION",
    "NO_WORKERS",
    "NO_CRYSTALS",
    "NO_LEARNING",
    "NO_STATISTICS",
    "NO_BAYES",
    "NO_EXTERNAL",
    "NO_CONFORMAL",
    "NO_ML",
    "NO_VNS_PHRASE",
    "NO_TEMPORAL_TEXTURE",
    "NO_QUORUM",
    "NO_QUEEN",
    "NO_MYSTIQUE",
    "NO_METABOLISM",
    "NO_POLLEN",
    "SIMPLE_MOMENTUM",
    "SIMPLE_REVERSION",
    "DETERMINISTIC_RANDOM",
    "NO_TRADE",
)

ADVERSARIAL_ATTACKS = (
    "SHUFFLE_EVIDENCE",
    "DELAY_EVIDENCE",
    "DUPLICATE_LINEAGE",
    "FALSE_UNISON",
    "STALE_WORLD_BINDING",
    "MISSING_VOICE",
    "ROOT_SUBSTITUTION",
    "TIME_SHIFT_PLACEBO",
)

MECHANISTIC_STATES = {
    "UNAVAILABLE",
    "AVAILABLE",
    "INVOKED",
    "INFLUENTIAL",
    "HISTORICALLY_USEFUL",
    "HISTORICALLY_HARMFUL",
    "HISTORICALLY_NEUTRAL",
    "INSUFFICIENT_EVIDENCE",
}


@dataclass(frozen=True)
class HistoricalWorldOutcome:
    world_state_id: str
    world_state_hash: str
    symbol: str
    timestamp_ms: int
    horizon_seconds: int

    direction: str
    abstain: bool
    selected: bool | None

    realized_net_bps: float | None

    envelope_id: str | None = None

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if not str(self.world_state_hash).startswith("sha256:"):
            raise ValueError(
                "historical_world_outcome_hash_invalid"
            )

        if self.execution_eligible:
            raise ValueError(
                "historical_world_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "historical_world_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalOrganProsecution:
    organ_id: str
    mask_id: str

    available: bool
    invoked_count: int
    non_default_output_count: int

    paired_world_count: int
    dependence_adjusted_world_count: int

    decision_change_count: int
    direction_change_count: int
    abstention_change_count: int
    selection_change_count: int

    full_hive_mean_net_bps: float | None
    ablated_mean_net_bps: float | None
    historical_paired_delta_bps: float | None
    uncertainty_bps: float | None

    classification: str

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.classification not in MECHANISTIC_STATES:
            raise ValueError(
                "unknown_historical_mechanistic_state"
            )

        if self.execution_eligible:
            raise ValueError(
                "historical_prosecution_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "historical_prosecution_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalCausalProsecutionReceipt:
    schema: str
    receipt_id: str

    mask_roster: tuple[str, ...]
    attack_roster: tuple[str, ...]

    organ_results: tuple[
        HistoricalOrganProsecution,
        ...
    ]

    survivor_ids: tuple[str, ...]

    historical_only: bool = True
    prospective_usefulness_proven: bool = False

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if tuple(self.mask_roster) != PAIRED_MASKS:
            raise ValueError(
                "historical_prosecution_mask_roster_not_frozen"
            )

        if tuple(self.attack_roster) != ADVERSARIAL_ATTACKS:
            raise ValueError(
                "historical_prosecution_attack_roster_not_frozen"
            )

        if not self.historical_only:
            raise ValueError(
                "historical_prosecution_must_remain_historical"
            )

        if self.prospective_usefulness_proven:
            raise ValueError(
                "historical_prosecution_cannot_prove_prospective_utility"
            )

        if self.execution_eligible:
            raise ValueError(
                "historical_prosecution_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "historical_prosecution_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_historical_result(
    *,
    available: bool,
    invoked_count: int,
    decision_change_count: int,
    historical_paired_delta_bps: float | None,
    minimum_paired_worlds_met: bool,
) -> str:
    if not available:
        return "UNAVAILABLE"

    if invoked_count <= 0:
        return "AVAILABLE"

    if decision_change_count <= 0:
        return "INVOKED"

    if not minimum_paired_worlds_met:
        return "INSUFFICIENT_EVIDENCE"

    if historical_paired_delta_bps is None:
        return "INFLUENTIAL"

    if historical_paired_delta_bps > 0.0:
        return "HISTORICALLY_USEFUL"

    if historical_paired_delta_bps < 0.0:
        return "HISTORICALLY_HARMFUL"

    return "HISTORICALLY_NEUTRAL"


def make_historical_prosecution_receipt(
    *,
    organ_results: Sequence[
        HistoricalOrganProsecution
    ],
) -> HistoricalCausalProsecutionReceipt:
    results = tuple(
        sorted(
            organ_results,
            key=lambda row: (
                row.organ_id,
                row.mask_id,
            ),
        )
    )

    survivors = tuple(
        sorted(
            row.organ_id
            for row in results
            if row.classification
            in {
                "HISTORICALLY_USEFUL",
                "INFLUENTIAL",
                "INSUFFICIENT_EVIDENCE",
            }
        )
    )

    body = {
        "mask_roster": PAIRED_MASKS,
        "attack_roster": ADVERSARIAL_ATTACKS,
        "organ_results": [
            row.to_dict()
            for row in results
        ],
        "survivors": survivors,
    }

    return HistoricalCausalProsecutionReceipt(
        schema=(
            "hivenance_full_organism_historical_causal_prosecution_v1"
        ),
        receipt_id=(
            "hcap_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        mask_roster=PAIRED_MASKS,
        attack_roster=ADVERSARIAL_ATTACKS,
        organ_results=results,
        survivor_ids=survivors,
        historical_only=True,
        prospective_usefulness_proven=False,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
