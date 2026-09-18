from __future__ import annotations

from strategies.relative_value_lab.contracts import RelativeMarketState
from strategies.relative_value_lab.forecast import OUMeanReversionForecaster, OUForecastConfig
from strategies.relative_value_lab.pair_lab import PairDiagnostics


def diagnostics(*, eligible: bool = True, stability: float = 0.8) -> PairDiagnostics:
    return PairDiagnostics(
        pair_id="A/USD__B/USD",
        samples=240,
        correlation_returns=0.7,
        hedge_alpha=0.2,
        hedge_ratio=1.0,
        hedge_r2=0.8,
        spread_mean=0.0,
        spread_std=0.01,
        spread_last=-0.02,
        spread_zscore=-2.0,
        ar1_intercept=0.0,
        ar1_phi=0.9,
        ar1_r2=0.8,
        ou_mean_reversion_speed_per_sec=0.02,
        ou_equilibrium=0.0,
        half_life_seconds=34.657,
        structural_break_score=0.2,
        structural_break_state="STABLE",
        stability_score=stability,
        eligible=eligible,
        rejection_reasons=() if eligible else ("relationship_not_eligible",),
    )


def state(spread: float = -0.02) -> RelativeMarketState:
    return RelativeMarketState(
        schema="hivenance_relative_market_state_v1",
        pair_id="A/USD__B/USD",
        timestamp_ms=123456,
        spread=spread,
        spread_zscore=-2.0,
        relative_volatility_bps=5.0,
        spread_cost_bps=2.0,
        route_cost_bps=4.0,
    )


def test_ou_forecast_predicts_reversion_toward_equilibrium():
    model = OUMeanReversionForecaster(
        OUForecastConfig(minimum_relationship_stability=0.4, minimum_net_edge_bps=0.5)
    )
    forecast = model.forecast(
        state=state(-0.02),
        diagnostics=diagnostics(),
        horizon_seconds=60,
        expected_cost_bps=4.0,
        residual_sigma_bps_per_sqrt_sec=0.5,
    )

    assert forecast.expected_relative_move_bps is not None
    assert forecast.expected_relative_move_bps > 0
    assert forecast.direction == "LONG_A_SHORT_B"
    assert forecast.expected_net_bps is not None and forecast.expected_net_bps > 0
    assert forecast.abstain is False
    assert forecast.execution_eligible is False
    assert forecast.calibration_state == "STRUCTURAL_BASELINE_UNCALIBRATED"


def test_ou_forecast_abstains_when_cost_exceeds_expected_reversion():
    model = OUMeanReversionForecaster(
        OUForecastConfig(minimum_relationship_stability=0.4, minimum_net_edge_bps=0.5)
    )
    forecast = model.forecast(
        state=state(-0.0001),
        diagnostics=diagnostics(),
        horizon_seconds=10,
        expected_cost_bps=20.0,
    )

    assert forecast.abstain is True
    assert forecast.reason == "insufficient_post_cost_forecast_edge"
    assert forecast.expected_net_bps is not None and forecast.expected_net_bps < 0


def test_ou_forecast_refuses_ineligible_relationship_even_with_large_dislocation():
    model = OUMeanReversionForecaster()
    forecast = model.forecast(
        state=state(-0.05),
        diagnostics=diagnostics(eligible=False),
        horizon_seconds=60,
        expected_cost_bps=1.0,
    )

    assert forecast.abstain is True
    assert forecast.direction == "ABSTAIN"
    assert forecast.expected_relative_move_bps is None
    assert forecast.execution_eligible is False
