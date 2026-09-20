import pytest

from strategies.relative_value_lab.historical_causal_prosecution import (
    HistoricalWorldOutcome,
)
from strategies.relative_value_lab.historical_pair_aggregation import (
    aggregate_historical_pairs,
)
from strategies.relative_value_lab.historical_paired_world import (
    score_historical_pair,
)


def pair(
    i,
    *,
    full_net=5.0,
    masked_net=2.0,
    changed=True,
):
    h = (
        "sha256:"
        + format(
            i + 1,
            "064x",
        )
    )

    full = HistoricalWorldOutcome(
        world_state_id=f"w{i}",
        world_state_hash=h,
        symbol="BTC/USD",
        timestamp_ms=1000 + i,
        horizon_seconds=300,
        direction="UP",
        abstain=False,
        selected=True,
        realized_net_bps=full_net,
    )

    masked = HistoricalWorldOutcome(
        world_state_id=f"w{i}",
        world_state_hash=h,
        symbol="BTC/USD",
        timestamp_ms=1000 + i,
        horizon_seconds=300,
        direction=(
            "DOWN"
            if changed
            else "UP"
        ),
        abstain=False,
        selected=True,
        realized_net_bps=masked_net,
    )

    return score_historical_pair(
        mask_id="NO_FLOW",
        full=full,
        masked=masked,
    )


def test_useful_organ_aggregation():
    rows = tuple(
        pair(i)
        for i in range(6)
    )

    result = aggregate_historical_pairs(
        organ_id="FLOW",
        mask_id="NO_FLOW",
        available=True,
        invoked_count=6,
        non_default_output_count=6,
        pairs=rows,
        minimum_paired_worlds=5,
    )

    assert result.paired_world_count == 6
    assert result.decision_change_count == 6
    assert result.direction_change_count == 6

    assert (
        result.historical_paired_delta_bps
        == 3.0
    )

    assert (
        result.classification
        == "HISTORICALLY_USEFUL"
    )


def test_negative_delta_classifies_harmful():
    rows = tuple(
        pair(
            i,
            full_net=1.0,
            masked_net=4.0,
        )
        for i in range(6)
    )

    result = aggregate_historical_pairs(
        organ_id="FLOW",
        mask_id="NO_FLOW",
        available=True,
        invoked_count=6,
        non_default_output_count=6,
        pairs=rows,
        minimum_paired_worlds=5,
    )

    assert (
        result.historical_paired_delta_bps
        == -3.0
    )

    assert (
        result.classification
        == "HISTORICALLY_HARMFUL"
    )


def test_underpowered_changed_organ_is_insufficient_not_useful():
    rows = tuple(
        pair(i)
        for i in range(3)
    )

    result = aggregate_historical_pairs(
        organ_id="FLOW",
        mask_id="NO_FLOW",
        available=True,
        invoked_count=3,
        non_default_output_count=3,
        pairs=rows,
        minimum_paired_worlds=5,
    )

    assert (
        result.classification
        == "INSUFFICIENT_EVIDENCE"
    )


def test_invoked_but_no_decision_effect_is_invoked_only():
    rows = tuple(
        pair(
            i,
            changed=False,
        )
        for i in range(6)
    )

    result = aggregate_historical_pairs(
        organ_id="FLOW",
        mask_id="NO_FLOW",
        available=True,
        invoked_count=6,
        non_default_output_count=6,
        pairs=rows,
        minimum_paired_worlds=5,
    )

    assert result.decision_change_count == 0
    assert result.classification == "INVOKED"


def test_dependence_adjusted_world_count_uses_clusters():
    rows = tuple(
        pair(i)
        for i in range(6)
    )

    result = aggregate_historical_pairs(
        organ_id="FLOW",
        mask_id="NO_FLOW",
        available=True,
        invoked_count=6,
        non_default_output_count=6,
        pairs=rows,
        minimum_paired_worlds=5,
        dependence_cluster_ids=(
            "cluster-a",
            "cluster-a",
            "cluster-b",
            "cluster-b",
            "cluster-c",
            "cluster-c",
        ),
    )

    assert (
        result.dependence_adjusted_world_count
        == 3
    )


def test_wrong_mask_pair_is_refused():
    row = pair(0)

    changed = type(row)(
        **{
            **row.__dict__,
            "mask_id": "NO_QUEEN",
        }
    )

    with pytest.raises(
        ValueError,
        match="mask_mismatch",
    ):
        aggregate_historical_pairs(
            organ_id="FLOW",
            mask_id="NO_FLOW",
            available=True,
            invoked_count=1,
            non_default_output_count=1,
            pairs=(changed,),
        )
