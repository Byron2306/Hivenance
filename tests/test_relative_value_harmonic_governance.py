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


def test_controls_do_not_count_as_independent_forecast_families():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="baseline_reversal_v1", horizon=10, predicted=2.0),
        prediction(model_id="baseline_continuation_v1", horizon=10, predicted=-2.0),
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=2.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)

    assert receipt.independent_families == ("structural",)
    assert receipt.state == "INSUFFICIENT"
    assert "insufficient_independent_forecast_families" in receipt.reasons
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_family_gets_one_global_vote_even_with_multiple_horizons():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=4.0),
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=30, predicted=4.0),
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=60, predicted=4.0),
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=120, predicted=4.0),
        prediction(model_id="relative_value_expanding_ridge_v1", horizon=10, predicted=-1.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)

    assert receipt.independent_families == ("statistical", "structural")
    # One structural family vote vs one statistical family vote -> global tie.
    assert receipt.direction == "ABSTAIN"


def test_resonant_state_requires_registered_family_agreement():
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

    assert receipt.direction == "LONG_A_SHORT_B"
    assert receipt.resonance_score >= cfg.min_resonance
    assert receipt.discord_score <= cfg.max_discord
    assert receipt.confidence >= cfg.min_confidence
    assert receipt.state == "RESONANT"
    assert receipt.execution_eligible is False


def test_forecast_flipping_increases_cadence_risk():
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
    assert receipt.direction_flip_rate > 0.70
    assert receipt.forecast_jitter > 0.0


def test_unregistered_challenger_does_not_silently_gain_independent_vote():
    engine = HarmonicForecastGovernance()
    rows = [
        prediction(model_id="relative_value_ou_mean_reversion_v1", horizon=10, predicted=2.0),
        prediction(model_id="mystery_super_model", horizon=10, predicted=2.0),
    ]
    receipt = engine.score(pair_id="A/USD__B/USD", timestamp_ms=1_000, predictions=rows)

    assert receipt.independent_families == ("structural",)
    assert receipt.state == "INSUFFICIENT"
