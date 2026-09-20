from __future__ import annotations

from dataclasses import replace

from strategies.volatility_breakout.learning_crystal_feedback import (
    apply_learning_prior_to_forecast,
    attach_learning_feedback,
    compile_learning_feedback,
    learning_crystal_rows,
)
from strategies.volatility_breakout.models import FeatureVector, Forecast


class FakeReuseGovernor:
    def __init__(self, rows):
        self.rows = dict(rows)
        self.calls = []

    def decide(self, **kwargs):
        self.calls.append(dict(kwargs))
        key = (kwargs["model_id"], int(kwargs["horizon_seconds"]))
        row = dict(self.rows.get(key) or {})
        return {
            "decision": row.get("decision", "no_prior_evidence"),
            "reason": row.get("reason", "fixture"),
            "model_id": kwargs["model_id"],
            "symbol": kwargs["symbol"],
            "regime_hint": kwargs["regime_hint"],
            "horizon_seconds": int(kwargs["horizon_seconds"]),
            "config_hash": "fixture-config",
            "sample_count": int(row.get("sample_count") or 0),
            "mean_realized_net_bps": row.get("mean_realized_net_bps"),
            "win_rate": row.get("win_rate"),
            "latest_settled_ts": row.get("latest_settled_ts"),
        }


def feature(ts=1_000_000):
    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=ts,
        price=100.0,
        realized_volatility_fast=0.01,
        realized_volatility_baseline=0.008,
        volatility_expansion=1.3,
        volume_zscore=0.8,
        trade_count_zscore=0.5,
        order_flow_imbalance=0.1,
        book_imbalance=0.1,
        spread_bps=3.0,
        depth_usd_25bps=1_000_000.0,
        quote_volume_24h=100_000_000.0,
        return_5=0.01,
        freshness_sec=1.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        complete=True,
        return_zscore=1.2,
        range_position=0.7,
        trend_slope=0.00001,
        atr_pct=0.01,
        reversal_return_1=-0.001,
        momentum_consistency=0.8,
        values={
            "regime_inputs": {
                "regime_hint": "trend_expansion",
                "liquidity_state": "deep",
                "participation_state": "expanding",
                "confidence": 0.8,
            },
            "symbol_class": "major",
            "cohort_bucket": "event_driven",
            "feature_version": "phase2.v1",
        },
    )


def forecast(*, abstain=False):
    return Forecast(
        symbol="BTC/USD",
        timestamp_ms=1_000_000,
        horizon_seconds=300,
        direction="ABSTAIN" if abstain else "UP",
        probability_positive_net=None if abstain else 0.55,
        expected_move_bps=None if abstain else 40.0,
        expected_cost_bps=10.0,
        expected_net_bps=None if abstain else 30.0,
        abstain=abstain,
        reason="fixture",
        model_id="model_a",
        hypothesis="breakout_continuation",
        raw_score=None if abstain else 0.6,
        uncertainty=1.0 if abstain else 0.4,
        calibration_state="FIXTURE",
        feature_version="phase2.v1",
        reasons=(),
        inputs={},
        execution_eligible=False,
    )


def test_positive_reuse_is_compiled_before_prediction_and_is_point_in_time():
    gov = FakeReuseGovernor({
        ("model_a", 300): {
            "decision": "exact_reuse_candidate",
            "sample_count": 8,
            "mean_realized_net_bps": 12.0,
            "win_rate": 0.75,
            "latest_settled_ts": 900.0,
        }
    })
    fb = compile_learning_feedback(
        feature(),
        model_ids=["model_a"],
        horizons=[300],
        reuse_governor=gov,
        max_age_sec=500.0,
        min_samples_for_reuse=5,
    )
    prior = fb["priors"]["model_a|300"]
    assert prior["lifecycle"] == "DETERMINISTIC_RESEARCH_REUSE_CANDIDATE"
    assert prior["support_score"] > 0
    assert prior["warning_score"] == 0
    assert prior["authority"] == "RESEARCH_PRIOR_ONLY"
    assert prior["execution_eligible"] is False
    assert gov.calls[0]["as_of_ts"] == 1000.0


def test_future_evidence_is_refused():
    gov = FakeReuseGovernor({
        ("model_a", 300): {
            "decision": "exact_reuse_candidate",
            "sample_count": 20,
            "mean_realized_net_bps": 50.0,
            "win_rate": 0.9,
            "latest_settled_ts": 1001.0,
        }
    })
    prior = compile_learning_feedback(
        feature(),
        model_ids=["model_a"],
        horizons=[300],
        reuse_governor=gov,
    )["priors"]["model_a|300"]
    assert prior["future_evidence_refused"] is True
    assert prior["support_score"] == 0
    assert prior["lifecycle"] == "REFUSED_FUTURE_EVIDENCE"


def test_stale_positive_reuse_is_demoted():
    gov = FakeReuseGovernor({
        ("model_a", 300): {
            "decision": "exact_reuse_candidate",
            "sample_count": 8,
            "mean_realized_net_bps": 12.0,
            "win_rate": 0.75,
            "latest_settled_ts": 100.0,
        }
    })
    prior = compile_learning_feedback(
        feature(),
        model_ids=["model_a"],
        horizons=[300],
        reuse_governor=gov,
        max_age_sec=100.0,
    )["priors"]["model_a|300"]
    assert prior["stale"] is True
    assert prior["support_score"] == 0
    assert prior["lifecycle"] == "CHALLENGED_STALE"


def test_positive_prior_strengthens_confidence_without_inventing_direction_or_move():
    fb = {
        "priors": {
            "model_a|300": {
                "support_score": 0.8,
                "warning_score": 0.0,
                "authority": "RESEARCH_PRIOR_ONLY",
            }
        }
    }
    f = attach_learning_feedback(feature(), fb)
    before = forecast()
    after = apply_learning_prior_to_forecast(before, f)
    assert after.direction == before.direction
    assert after.expected_move_bps == before.expected_move_bps
    assert after.expected_net_bps == before.expected_net_bps
    assert after.probability_positive_net > before.probability_positive_net
    assert after.uncertainty < before.uncertainty
    assert after.execution_eligible is False


def test_negative_prior_can_veto_but_cannot_flip_direction():
    fb = {
        "priors": {
            "model_a|300": {
                "support_score": 0.0,
                "warning_score": 0.9,
                "authority": "RESEARCH_PRIOR_ONLY",
            }
        }
    }
    after = apply_learning_prior_to_forecast(
        forecast(),
        attach_learning_feedback(feature(), fb),
    )
    assert after.abstain is True
    assert after.direction == "ABSTAIN"
    assert after.reason == "learning_prior_negative_reuse_veto"
    assert after.execution_eligible is False


def test_positive_prior_does_not_resurrect_an_abstaining_forecast_by_itself():
    fb = {
        "priors": {
            "model_a|300": {
                "support_score": 1.0,
                "warning_score": 0.0,
                "authority": "RESEARCH_PRIOR_ONLY",
            }
        }
    }
    before = forecast(abstain=True)
    after = apply_learning_prior_to_forecast(
        before,
        attach_learning_feedback(feature(), fb),
    )
    assert after.abstain is True
    assert after.direction == "ABSTAIN"
    assert after.execution_eligible is False


def test_learning_crystal_rows_are_deterministic_and_research_only():
    gov = FakeReuseGovernor({
        ("model_a", 300): {
            "decision": "exact_reuse_candidate",
            "sample_count": 8,
            "mean_realized_net_bps": 12.0,
            "win_rate": 0.75,
            "latest_settled_ts": 900.0,
        }
    })
    f = feature()
    fb = compile_learning_feedback(
        f,
        model_ids=["model_a"],
        horizons=[300],
        reuse_governor=gov,
        max_age_sec=500.0,
    )
    a = learning_crystal_rows(f, fb, venue="kraken")
    b = learning_crystal_rows(f, fb, venue="kraken")
    assert a == b
    assert len(a) == 1
    assert a[0]["verification_state"] == "reusable_candidate"
    assert a[0]["authority"] == "research_prior_only"
    assert a[0]["payload"]["execution_eligible"] is False
    assert a[0]["payload"]["promotion_eligible"] is False
