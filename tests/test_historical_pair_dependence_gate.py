from strategies.relative_value_lab.historical_pair_aggregation import (
    aggregate_historical_pairs,
)
from strategies.relative_value_lab.historical_paired_world import (
    HistoricalPairedWorldDelta,
)


def pair(i):
    return HistoricalPairedWorldDelta(
        schema="test",
        pair_id=f"p{i}",
        mask_id="NO_TEST",
        world_state_id=f"w{i}",
        world_state_hash="sha256:" + "a" * 64,
        symbol=f"S{i}",
        timestamp_ms=1000 + i,
        horizon_seconds=300,
        decision_changed=True,
        direction_changed=True,
        abstention_changed=True,
        selection_changed=False,
        full_direction="ABSTAIN",
        masked_direction="UP",
        full_abstain=True,
        masked_abstain=False,
        full_selected=None,
        masked_selected=None,
        full_net_bps=0.0,
        masked_net_bps=-10.0,
        paired_delta_bps=10.0,
        outcome_comparable=True,
        execution_eligible=False,
        promotion_eligible=False,
    )


def test_many_correlated_pairs_do_not_satisfy_independence_gate():
    rows = tuple(
        pair(i)
        for i in range(10)
    )

    result = aggregate_historical_pairs(
        organ_id="test",
        mask_id="NO_TEST",
        available=True,
        invoked_count=10,
        non_default_output_count=10,
        pairs=rows,
        minimum_paired_worlds=5,
        dependence_cluster_ids=(
            "same_cohort",
        ) * 10,
    )

    assert (
        result.dependence_adjusted_world_count
        == 1
    )

    assert (
        result.classification
        != "HISTORICALLY_USEFUL"
    )
