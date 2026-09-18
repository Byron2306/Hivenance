from __future__ import annotations

from strategies.relative_value_lab.contracts import ForwardRelativeForecast, RelativeMarketState
from strategies.relative_value_lab.settlement import ProspectiveForecastSettler


def state(ts: int, spread: float) -> RelativeMarketState:
    return RelativeMarketState(
        schema="hivenance_relative_market_state_v1",
        pair_id="A/USD__B/USD",
        timestamp_ms=ts,
        spread=spread,
        spread_zscore=None,
    )


def forecast() -> ForwardRelativeForecast:
    return ForwardRelativeForecast(
        schema="hivenance_forward_relative_forecast_v1",
        forecast_id="rvf_test",
        pair_id="A/USD__B/USD",
        timestamp_ms=1_000,
        horizon_seconds=10,
        model_id="test",
        expected_relative_move_bps=8.0,
        prediction_lower_bps=None,
        prediction_upper_bps=None,
        probability_positive_gross=None,
        expected_cost_bps=3.0,
        expected_net_bps=5.0,
        uncertainty=None,
        calibration_state="TEST",
        abstain=False,
        reason="test",
        direction="LONG_A_SHORT_B",
    )


def test_settler_refuses_to_score_before_future_horizon():
    settler = ProspectiveForecastSettler()
    settler.register(forecast=forecast(), state=state(1_000, -0.01))
    assert settler.settle(state(10_999, -0.0095)) == []
    assert settler.pending() == 1


def test_settler_scores_only_after_target_and_subtracts_frozen_cost():
    settler = ProspectiveForecastSettler()
    settler.register(forecast=forecast(), state=state(1_000, -0.01))
    rows = settler.settle(state(11_000, -0.009))
    assert len(rows) == 1
    row = rows[0]
    assert round(row.realized_signed_move_bps, 6) == 10.0
    assert round(row.realized_directional_gross_bps or 0.0, 6) == 10.0
    assert round(row.realized_directional_net_bps or 0.0, 6) == 7.0
    assert round(row.forecast_error_bps or 0.0, 6) == 2.0
    assert row.execution_eligible is False
    assert settler.pending() == 0


def test_settler_does_not_double_settle():
    settler = ProspectiveForecastSettler()
    settler.register(forecast=forecast(), state=state(1_000, -0.01))
    assert len(settler.settle(state(11_000, -0.009))) == 1
    assert settler.settle(state(12_000, -0.008)) == []
