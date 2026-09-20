"""Aggregate same-world Phase 12 paired deltas into one organ prosecution row."""

from __future__ import annotations

import math
import statistics
from typing import Sequence

from .historical_causal_prosecution import (
    HistoricalOrganProsecution,
    classify_historical_result,
)
from .historical_paired_world import (
    HistoricalPairedWorldDelta,
)


def _mean(values):
    return (
        statistics.fmean(values)
        if values
        else None
    )


def _uncertainty(values):
    """Simple standard error, historical descriptive uncertainty only."""

    if len(values) < 2:
        return None

    return (
        statistics.stdev(values)
        / math.sqrt(len(values))
    )


def aggregate_historical_pairs(
    *,
    organ_id: str,
    mask_id: str,
    available: bool,
    invoked_count: int,
    non_default_output_count: int,
    pairs: Sequence[
        HistoricalPairedWorldDelta
    ],
    minimum_paired_worlds: int = 5,
    dependence_cluster_ids: Sequence[str] | None = None,
) -> HistoricalOrganProsecution:

    rows = tuple(pairs)

    for row in rows:
        if row.mask_id != mask_id:
            raise ValueError(
                "historical_pair_mask_mismatch"
            )

    comparable = tuple(
        row
        for row in rows
        if row.outcome_comparable
        and row.paired_delta_bps
        is not None
    )

    deltas = tuple(
        float(row.paired_delta_bps)
        for row in comparable
    )

    full_values = tuple(
        float(row.full_net_bps)
        for row in comparable
        if row.full_net_bps
        is not None
    )

    masked_values = tuple(
        float(row.masked_net_bps)
        for row in comparable
        if row.masked_net_bps
        is not None
    )

    if dependence_cluster_ids is None:
        dependence_adjusted = len(
            {
                row.world_state_id
                for row in rows
            }
        )

    else:
        if len(
            dependence_cluster_ids
        ) != len(rows):
            raise ValueError(
                "dependence_cluster_length_mismatch"
            )

        dependence_adjusted = len(
            set(
                map(
                    str,
                    dependence_cluster_ids,
                )
            )
        )

    paired_delta = _mean(
        deltas
    )

    classification = (
        classify_historical_result(
            available=available,
            invoked_count=invoked_count,
            decision_change_count=sum(
                1
                for row in rows
                if row.decision_changed
            ),
            historical_paired_delta_bps=(
                paired_delta
            ),
            minimum_paired_worlds_met=(
                dependence_adjusted
                >= int(
                    minimum_paired_worlds
                )
            ),
        )
    )

    return HistoricalOrganProsecution(
        organ_id=str(organ_id),
        mask_id=str(mask_id),
        available=bool(available),
        invoked_count=int(
            invoked_count
        ),
        non_default_output_count=int(
            non_default_output_count
        ),
        paired_world_count=len(
            comparable
        ),
        dependence_adjusted_world_count=(
            dependence_adjusted
        ),
        decision_change_count=sum(
            1
            for row in rows
            if row.decision_changed
        ),
        direction_change_count=sum(
            1
            for row in rows
            if row.direction_changed
        ),
        abstention_change_count=sum(
            1
            for row in rows
            if row.abstention_changed
        ),
        selection_change_count=sum(
            1
            for row in rows
            if row.selection_changed
        ),
        full_hive_mean_net_bps=(
            _mean(full_values)
        ),
        ablated_mean_net_bps=(
            _mean(masked_values)
        ),
        historical_paired_delta_bps=(
            paired_delta
        ),
        uncertainty_bps=(
            _uncertainty(deltas)
        ),
        classification=classification,
        execution_eligible=False,
        promotion_eligible=False,
    )
