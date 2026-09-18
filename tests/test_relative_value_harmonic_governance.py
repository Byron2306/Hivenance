from __future__ import annotations

from strategies.relative_value_lab.evaluation import WalkForwardPrediction
from strategies.relative_value_lab.harmonic_governance import (
    HarmonicForecastGovernance,
    HarmonicGovernanceConfig,
)


def prediction(
    *,
    model_id: str,
    horizon: int,
    predicted: float,
    realized: float = 1.0,
    ts: int = 1_000,
) -> WalkForwardPrediction:
    return WalkForwardPrediction(
        schema="hivenance_relative_value_walk_forward_prediction_v1",
        example_id=f"{model_id}-{horizon}-{ts}",
        pair_id="A/USD__B/USD",
        timestamp_ms=ts,
        horizon_seconds=horizon,
        model_id=model_id,
        predicted_signed_bps=predicted,
        realized_signed_bps=realized,
        directional_gross_bps=realized,
        spread_cost_proxy_bps=1.0,
        directional_after_spread_proxy_bps=0.0,
        train_samples=100,
    )


def by_horizon(receipt, horizon):
    return next(state for state in receipt.horizon_states if state.horizon_seconds == horizon)


def test_controls_do_not_count_as_independent_forecast_families():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="baseline_reversal_v1", horizon=10, predicted=2.0),
        prediction(model_id="baseline_continuation_v1", horizon=10, predicted=-2.0),
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=2.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)

    assert receipt.independent_families == ("structural",)
    assert by_horizon(receipt, 10).state == "INSUFFICIENT"
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_global_receipt_has_no_market_direction_field():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=4.0),
        prediction(model_id="relative_value_expanding_ridge_v1", horizon=10, predicted=3.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)
    payload = receipt.to_dict()
    assert "direction" not in payload
    assert by_horizon(receipt, 10).direction == "LONG_A_SHORT_B"


def test_opposite_micro_and_macro_directions_can_coexist():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=3.0),
        prediction(model_id="relative_value_expanding_ridge_v1", horizon=10, predicted=2.0),
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=120, predicted=-3.0),
        prediction(model_id="relative_value_expanding_ridge_v1", horizon=120, predicted=-2.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)

    assert by_horizon(receipt, 10).direction == "LONG_A_SHORT_B"
    assert by_horizon(receipt, 120).direction == "LONG_B_SHORT_A"
    assert receipt.spectrum.micro is not None
    assert receipt.spectrum.macro is not None
    assert "direction" not in receipt.to_dict()


def test_resonant_state_requires_registered_family_agreement_within_horizon():
    cfg = HarmonicGovernanceConfig(
        min_resonance=0.55,
        max_discord=0.55,
        min_confidence=0.40,
    )
    engine = HarmonicForecastGovernance(cfg)
    for step in range(10):
        ts = 1_000 + step * 5_000
        rows = [
            prediction(
                model_id="relative_value_ou_mean_reversion_v1",
                horizon=10,
                predicted=2.0,
                ts=ts,
            ),
            prediction(
                model_id="relative_value_expanding_ridge_v1",
                horizon=10,
                predicted=1.5,
                ts=ts,
            ),
        ]
        receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=ts, predictions=rows)

    state = by_horizon(receipt, 10)
    assert state.direction == "LONG_A_SHORT_B"
    assert state.resonance_score >= cfg.min_resonance
    assert state.discord_score <= cfg.max_discord
    assert state.confidence >= cfg.min_confidence
    assert state.state == "RESONANT"
    assert receipt.execution_eligible is False


def test_forecast_flipping_increases_same_horizon_cadence_risk():
    cfg = HarmonicGovernanceConfig(min_resonance=0.0, max_discord=1.0, min_confidence=0.0)
    engine = HarmonicForecastGovernance(cfg)
    receipt = None
    for step in range(12):
        ts = 1_000 + step * 5_000
        sign = 1.0 if step % 2 == 0 else -1.0
        rows = [
            prediction(
                model_id="relative_value_ou_mean_reversion_v1",
                horizon=10,
                predicted=2.0 * sign,
                ts=ts,
            ),
            prediction(
                model_id="relative_value_expanding_ridge_v1",
                horizon=10,
                predicted=1.5 * sign,
                ts=ts,
            ),
        ]
        receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=ts, predictions=rows)

    assert receipt is not None
    state = by_horizon(receipt, 10)
    assert state.direction_flip_rate > 0.70
    assert state.forecast_jitter > 0.0


def test_control_dissent_compares_with_same_horizon_only():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=2.0),
        prediction(model_id="relative_value_expanding_ridge_v1", horizon=10, predicted=1.5),
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=120, predicted=-2.0),
        prediction(model_id="relative_value_expanding_ridge_v1", horizon=120, predicted=-1.5),
        prediction(model_id="baseline_continuation_v1", horizon=10, predicted=1.0),
        prediction(model_id="baseline_continuation_v1", horizon=120, predicted=1.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)
    assert receipt.control_dissent["baseline_continuation_v1:10s"]["agrees_with_same_horizon_direction"] is True
    assert receipt.control_dissent["baseline_continuation_v1:120s"]["agrees_with_same_horizon_direction"] is False


def test_unregistered_challenger_does_not_silently_gain_independent_vote():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=2.0),
        prediction(model_id="mystery_super_model", horizon=10, predicted=2.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)

    assert receipt.independent_families == ("structural",)
    assert by_horizon(receipt, 10).state == "INSUFFICIENT"
