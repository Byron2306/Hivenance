from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .historical_causal_prosecution import (
    HistoricalOrganProsecution,
    HistoricalWorldOutcome,
    classify_historical_result,
    make_historical_prosecution_receipt,
)
from .organ_utility_census import build_organ_utility_census


MASK_TO_ORGAN = {
    "NO_LONG_HORIZON_LATTICE": "long_horizon_lattice",
    "NO_CEX_ORACLE": "cex_multi_horizon_oracle",
    "NO_COMPARISON": "comparison_engine",
    "NO_COIN_SELECTOR": "coin_selector",
    "NO_REGIME": "regime_oracle",
    "NO_FLOW": "flow",
    "NO_LIQUIDITY": "liquidity",
    "NO_VOLATILITY": "volatility",
    "NO_CROSS_MARKET": "cross_market",
    "NO_TEMPORAL_PARTICIPATION": "temporal_participation_bee",
    "NO_WORKERS": "strategy_workers",
    "NO_CRYSTALS": "crystals",
    "NO_LEARNING": "learning_memory",
    "NO_STATISTICS": "statistics_bee",
    "NO_BAYES": "bayesian_regime_filter",
    "NO_EXTERNAL": "external_statistics_sensorium",
    "NO_CONFORMAL": "stochastic_calibration",
    "NO_ML": "ml_challenger",
    "NO_VNS_PHRASE": "vns_temporal_texture",
    "NO_TEMPORAL_TEXTURE": "vns_temporal_texture",
    "NO_QUORUM": "polyphonic_quorum",
    "NO_QUEEN": "conducting_queen",
    "NO_MYSTIQUE": "mystique",
    "NO_METABOLISM": "cognitive_metabolism",
    "NO_POLLEN": "pollen_economy",
}


@dataclass(frozen=True)
class CensusRun:
    prosecution: Any
    utility_census: Any
    paired_masks: tuple[str, ...]
    skipped_masks: tuple[str, ...]
    execution_eligible: bool = False
    promotion_eligible: bool = False


def _key(row: HistoricalWorldOutcome) -> tuple[str, str, int, int, str]:
    return (
        str(row.world_state_id),
        str(row.symbol),
        int(row.timestamp_ms),
        int(row.horizon_seconds),
        str(row.envelope_id or ""),
    )


def _decision(row: HistoricalWorldOutcome) -> tuple[bool, str, bool | None]:
    return (
        bool(row.abstain),
        str(row.direction).upper(),
        row.selected,
    )


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def _uncertainty(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.pstdev(values) / math.sqrt(len(values))


def _dependence_adjusted_count(rows: Sequence[HistoricalWorldOutcome]) -> int:
    # Conservative world buckets: same symbol/horizon/timestamp day collapse.
    buckets = {
        (
            str(row.symbol),
            int(row.horizon_seconds),
            int(row.timestamp_ms) // 86_400_000,
        )
        for row in rows
    }
    return len(buckets)


def prosecute_mask(
    *,
    mask_id: str,
    full_hive: Sequence[HistoricalWorldOutcome],
    ablated: Sequence[HistoricalWorldOutcome],
    invoked_count: int,
    non_default_output_count: int | None = None,
    minimum_independent_worlds: int = 5,
    organ_id: str | None = None,
) -> HistoricalOrganProsecution:
    full_map = {_key(row): row for row in full_hive}
    masked_map = {_key(row): row for row in ablated}

    common = sorted(set(full_map) & set(masked_map))
    paired_full = [full_map[key] for key in common]
    paired_masked = [masked_map[key] for key in common]

    decision_changes = 0
    direction_changes = 0
    abstention_changes = 0
    selection_changes = 0
    deltas: list[float] = []

    full_nets: list[float] = []
    masked_nets: list[float] = []

    for full, blind in zip(paired_full, paired_masked):
        if _decision(full) != _decision(blind):
            decision_changes += 1
        if str(full.direction).upper() != str(blind.direction).upper():
            direction_changes += 1
        if bool(full.abstain) != bool(blind.abstain):
            abstention_changes += 1
        if full.selected != blind.selected:
            selection_changes += 1

        if full.realized_net_bps is not None and blind.realized_net_bps is not None:
            a = float(full.realized_net_bps)
            b = float(blind.realized_net_bps)
            full_nets.append(a)
            masked_nets.append(b)
            deltas.append(a - b)

    dep_n = _dependence_adjusted_count(paired_full)
    delta = _mean(deltas)
    classification = classify_historical_result(
        available=bool(common),
        invoked_count=int(invoked_count),
        decision_change_count=decision_changes,
        historical_paired_delta_bps=delta,
        minimum_paired_worlds_met=(dep_n >= int(minimum_independent_worlds)),
    )

    return HistoricalOrganProsecution(
        organ_id=str(organ_id or MASK_TO_ORGAN.get(mask_id, mask_id.lower())),
        mask_id=str(mask_id),
        available=bool(common),
        invoked_count=int(invoked_count),
        non_default_output_count=int(
            invoked_count if non_default_output_count is None else non_default_output_count
        ),
        paired_world_count=len(common),
        dependence_adjusted_world_count=dep_n,
        decision_change_count=decision_changes,
        direction_change_count=direction_changes,
        abstention_change_count=abstention_changes,
        selection_change_count=selection_changes,
        full_hive_mean_net_bps=_mean(full_nets),
        ablated_mean_net_bps=_mean(masked_nets),
        historical_paired_delta_bps=delta,
        uncertainty_bps=_uncertainty(deltas),
        classification=classification,
    )


def run_full_organism_census(
    *,
    outcomes_by_mask: Mapping[str, Sequence[HistoricalWorldOutcome]],
    invocation_counts: Mapping[str, int] | None = None,
    non_default_output_counts: Mapping[str, int] | None = None,
    minimum_independent_worlds: int = 5,
) -> CensusRun:
    if "FULL_HIVE" not in outcomes_by_mask:
        raise ValueError("full_organism_census_requires_full_hive")

    invocation_counts = dict(invocation_counts or {})
    non_default_output_counts = dict(non_default_output_counts or {})
    full = tuple(outcomes_by_mask["FULL_HIVE"])

    rows: list[HistoricalOrganProsecution] = []
    paired_masks: list[str] = []
    skipped_masks: list[str] = []

    for mask_id, organ_id in MASK_TO_ORGAN.items():
        masked = outcomes_by_mask.get(mask_id)
        if masked is None:
            skipped_masks.append(mask_id)
            continue

        row = prosecute_mask(
            mask_id=mask_id,
            organ_id=organ_id,
            full_hive=full,
            ablated=tuple(masked),
            invoked_count=int(invocation_counts.get(mask_id, 0)),
            non_default_output_count=non_default_output_counts.get(mask_id),
            minimum_independent_worlds=int(minimum_independent_worlds),
        )
        rows.append(row)
        paired_masks.append(mask_id)

    prosecution = make_historical_prosecution_receipt(
        organ_results=tuple(rows),
    )

    aliases = {
        "flow": "feature_engine",
        "liquidity": "feature_engine",
        "volatility": "feature_engine",
        "cross_market": "feature_engine",
        "regime_oracle": "bayesian_regime_filter",
        "bayesian_regime_filter": "bayesian_regime_filter",
        "external_statistics_sensorium": "external_statistics_sensorium",
        "stochastic_calibration": "stochastic_calibration",
        "strategy_workers": "strategy_workers",
        "vns_temporal_texture": "vns_temporal_texture",
    }

    utility = build_organ_utility_census(
        prosecution.organ_results,
        topology_aliases=aliases,
    )

    return CensusRun(
        prosecution=prosecution,
        utility_census=utility,
        paired_masks=tuple(paired_masks),
        skipped_masks=tuple(skipped_masks),
        execution_eligible=False,
        promotion_eligible=False,
    )
