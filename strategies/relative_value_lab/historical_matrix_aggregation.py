"""Aggregate complete Phase-12 matrix results across historical worlds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .historical_causal_prosecution import (
    HistoricalOrganProsecution,
    make_historical_prosecution_receipt,
)
from .historical_pair_aggregation import (
    aggregate_historical_pairs,
)
from .historical_prosecution_matrix import (
    HistoricalMatrixCaseResult,
)


MASK_TO_ORGAN = {
    "NO_LONG_HORIZON_LATTICE":
        "LONG_HORIZON_LATTICE",
    "NO_CEX_ORACLE":
        "CEX_ORACLE",
    "NO_COMPARISON":
        "COMPARISON",
    "NO_COIN_SELECTOR":
        "COIN_SELECTOR",
    "NO_REGIME":
        "REGIME",
    "NO_FLOW":
        "FLOW",
    "NO_LIQUIDITY":
        "LIQUIDITY",
    "NO_VOLATILITY":
        "VOLATILITY",
    "NO_CROSS_MARKET":
        "CROSS_MARKET",
    "NO_TEMPORAL_PARTICIPATION":
        "TEMPORAL_PARTICIPATION",
    "NO_WORKERS":
        "WORKERS",
    "NO_CRYSTALS":
        "CRYSTALS",
    "NO_LEARNING":
        "LEARNING",
    "NO_VNS_PHRASE":
        "VNS_PHRASE",
    "NO_TEMPORAL_TEXTURE":
        "TEMPORAL_TEXTURE",
    "NO_QUORUM":
        "QUORUM",
    "NO_QUEEN":
        "QUEEN",
    "NO_MYSTIQUE":
        "MYSTIQUE",
    "NO_METABOLISM":
        "METABOLISM",
    "NO_POLLEN":
        "POLLEN",
}


@dataclass(frozen=True)
class HistoricalMatrixAggregate:
    organ_results: tuple[
        HistoricalOrganProsecution,
        ...
    ]

    control_mask_pair_counts: Mapping[str, int]

    receipt: object

    execution_eligible: bool = False
    promotion_eligible: bool = False


def aggregate_historical_matrix(
    *,
    cases: Sequence[
        HistoricalMatrixCaseResult
    ],
    invocation_counts:
        Mapping[str, int],
    non_default_output_counts:
        Mapping[str, int],
    availability:
        Mapping[str, bool],
    minimum_paired_worlds: int = 5,
) -> HistoricalMatrixAggregate:

    rows_by_mask = {}

    clusters_by_mask = {}

    for case in cases:
        for row in case.paired_deltas:
            rows_by_mask.setdefault(
                row.mask_id,
                [],
            ).append(row)

            clusters_by_mask.setdefault(
                row.mask_id,
                [],
            ).append(
                case.dependence_cluster_id
            )

    organ_results = []

    for mask_id, organ_id in (
        MASK_TO_ORGAN.items()
    ):
        rows = tuple(
            rows_by_mask.get(
                mask_id,
                (),
            )
        )

        organ_results.append(
            aggregate_historical_pairs(
                organ_id=organ_id,
                mask_id=mask_id,
                available=bool(
                    availability.get(
                        organ_id,
                        False,
                    )
                ),
                invoked_count=int(
                    invocation_counts.get(
                        organ_id,
                        0,
                    )
                ),
                non_default_output_count=int(
                    non_default_output_counts.get(
                        organ_id,
                        0,
                    )
                ),
                pairs=rows,
                minimum_paired_worlds=(
                    minimum_paired_worlds
                ),
                dependence_cluster_ids=tuple(
                    clusters_by_mask.get(
                        mask_id,
                        (),
                    )
                ),
            )
        )

    control_masks = (
        "SIMPLE_MOMENTUM",
        "SIMPLE_REVERSION",
        "DETERMINISTIC_RANDOM",
        "NO_TRADE",
    )

    control_counts = {
        mask: len(
            rows_by_mask.get(
                mask,
                (),
            )
        )
        for mask in control_masks
    }

    receipt = (
        make_historical_prosecution_receipt(
            organ_results=(
                organ_results
            )
        )
    )

    return HistoricalMatrixAggregate(
        organ_results=tuple(
            organ_results
        ),
        control_mask_pair_counts=(
            control_counts
        ),
        receipt=receipt,
        execution_eligible=False,
        promotion_eligible=False,
    )
