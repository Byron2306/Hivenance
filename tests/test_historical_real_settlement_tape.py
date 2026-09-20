import pytest

from strategies.relative_value_lab.historical_real_settlement_tape import (
    real_settlement_truth,
)
from strategies.relative_value_lab.historical_real_corpus import (
    HistoricalCorpusCase,
)


def case(
    *,
    entry=100.0,
    exit_price=102.0,
    gross_abs=200.0,
    cost=20.0,
):
    return HistoricalCorpusCase(
        case_id="c1",
        freeze_id="f1",
        settlement_id="s1",
        observation_run_id="obs1",
        symbol="BTC/USD",
        selected=True,
        selector_rank=1,
        blind_rank=5,
        blind_selected=False,
        observed_ts=1000.0,
        target_ts=1300.0,
        settled_ts=1301.0,
        horizon_seconds=300,
        world_state_id="ws1",
        world_state_hash=(
            "sha256:" + "a" * 64
        ),
        evidence_root=(
            "sha256:" + "b" * 64
        ),
        entry_price=entry,
        exit_price=exit_price,
        predicted_roundtrip_cost_bps=10.0,
        net_opportunity_bps=(
            gross_abs - cost
        ),
        gross_absolute_move_bps=(
            gross_abs
        ),
        regime="trend",
        freeze_payload={
            "observed_at_ms": 1_000_000,
        },
        settlement_payload={
            "realized_roundtrip_cost_bps":
                cost,
        },
        observation_snapshot={},
        matching_forecasts=(),
        matching_outcomes=(),
    )


def test_signed_future_move_is_recovered_from_prices():
    truth = real_settlement_truth(
        case()
    )

    assert (
        truth.realized_signed_move_bps
        == pytest.approx(200.0)
    )

    assert (
        truth.absolute_move_error_bps
        == pytest.approx(0.0)
    )


def test_negative_future_move_remains_negative():
    truth = real_settlement_truth(
        case(
            exit_price=98.0,
            gross_abs=200.0,
        )
    )

    assert (
        truth.realized_signed_move_bps
        == pytest.approx(-200.0)
    )


def test_flat_future_move_remains_flat():
    truth = real_settlement_truth(
        case(
            exit_price=100.0,
            gross_abs=0.0,
        )
    )

    assert (
        truth.realized_signed_move_bps
        == pytest.approx(0.0)
    )


def test_realized_cost_not_predicted_cost_drives_tape():
    truth = real_settlement_truth(
        case(
            cost=37.0,
        )
    )

    tape = (
        truth.to_settlement_tape()
    )

    assert (
        tape.expected_cost_bps
        == pytest.approx(37.0)
    )


def test_historical_prediction_direction_is_explicitly_not_frozen():
    truth = real_settlement_truth(
        case()
    )

    assert (
        truth.historical_direction_frozen
        is False
    )

    assert (
        truth.retrospective_reconstruction_only
        is True
    )


def test_real_tape_never_grants_authority():
    truth = real_settlement_truth(
        case()
    )

    assert truth.execution_eligible is False
    assert truth.promotion_eligible is False
