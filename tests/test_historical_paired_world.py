import pytest

from strategies.relative_value_lab.historical_causal_prosecution import (
    HistoricalWorldOutcome,
)
from strategies.relative_value_lab.historical_paired_world import (
    score_historical_pair,
)


HASH = "sha256:" + "a" * 64


def outcome(
    *,
    world="w1",
    world_hash=HASH,
    symbol="BTC/USD",
    ts=1000,
    horizon=300,
    direction="UP",
    abstain=False,
    selected=True,
    net=5.0,
):
    return HistoricalWorldOutcome(
        world_state_id=world,
        world_state_hash=world_hash,
        symbol=symbol,
        timestamp_ms=ts,
        horizon_seconds=horizon,
        direction=direction,
        abstain=abstain,
        selected=selected,
        realized_net_bps=net,
    )


def test_same_world_pair_measures_all_changes():
    row = score_historical_pair(
        mask_id="NO_FLOW",
        full=outcome(),
        masked=outcome(
            direction="DOWN",
            abstain=True,
            selected=False,
            net=-3.0,
        ),
    )

    assert row.decision_changed is True
    assert row.direction_changed is True
    assert row.abstention_changed is True
    assert row.selection_changed is True

    assert row.paired_delta_bps == 8.0
    assert row.outcome_comparable is True


def test_no_change_pair_is_explicit():
    row = score_historical_pair(
        mask_id="NO_FLOW",
        full=outcome(),
        masked=outcome(),
    )

    assert row.decision_changed is False
    assert row.direction_changed is False
    assert row.abstention_changed is False
    assert row.selection_changed is False

    assert row.paired_delta_bps == 0.0


def test_missing_outcome_keeps_mechanistic_pair_but_not_economic_delta():
    row = score_historical_pair(
        mask_id="NO_FLOW",
        full=outcome(net=5.0),
        masked=outcome(net=None),
    )

    assert row.outcome_comparable is False
    assert row.paired_delta_bps is None


@pytest.mark.parametrize(
    "field,value,error",
    [
        (
            "world",
            "w2",
            "same_world_id",
        ),
        (
            "world_hash",
            "sha256:" + "b" * 64,
            "same_world_hash",
        ),
        (
            "symbol",
            "ETH/USD",
            "same_symbol",
        ),
        (
            "ts",
            2000,
            "same_timestamp",
        ),
        (
            "horizon",
            3600,
            "same_horizon",
        ),
    ],
)
def test_pair_refuses_nonidentical_world_coordinates(
    field,
    value,
    error,
):
    kwargs = {field: value}

    with pytest.raises(
        ValueError,
        match=error,
    ):
        score_historical_pair(
            mask_id="NO_FLOW",
            full=outcome(),
            masked=outcome(
                **kwargs
            ),
        )


def test_pair_never_grants_authority():
    row = score_historical_pair(
        mask_id="NO_FLOW",
        full=outcome(),
        masked=outcome(),
    )

    assert row.execution_eligible is False
    assert row.promotion_eligible is False
