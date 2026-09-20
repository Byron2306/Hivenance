from strategies.volatility_breakout.hypothesis_models import _regime_confidence
from strategies.volatility_breakout.models import FeatureVector


def _feature(regime_context):
    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=1000,
        price=100.0,
        realized_volatility_fast=.01,
        realized_volatility_baseline=.01,
        volatility_expansion=1.0,
        volume_zscore=0.0,
        trade_count_zscore=None,
        order_flow_imbalance=None,
        book_imbalance=0.0,
        spread_bps=2.0,
        depth_usd_25bps=1_000_000.0,
        quote_volume_24h=100_000_000.0,
        return_5=.001,
        freshness_sec=0.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        values={"regime_context":regime_context},
        complete=True,
    )


def test_bayesian_posterior_is_context_only_for_hypothesis_gate():
    calm={
        "deterministic_hint":"trend_expansion",
        "deterministic_confidence":.8,
        "bayesian_probabilities":{"TREND":.9,"MEAN_REVERSION":.03,"TRANSITION":.04,"STRESS":.03},
        "dominant_posterior_regime":"TREND",
        "posterior_entropy":.2,
        "change_point_probability":.05,
        "disagreement_score":.08,
        "context_id":"c1",
    }
    hostile={
        **calm,
        "bayesian_probabilities":{"TREND":.01,"MEAN_REVERSION":.79,"TRANSITION":.1,"STRESS":.1},
        "dominant_posterior_regime":"MEAN_REVERSION",
        "posterior_entropy":.9,
        "change_point_probability":.99,
        "disagreement_score":.99,
        "context_id":"c2",
    }
    assert _regime_confidence(_feature(calm))==.8
    assert _regime_confidence(_feature(hostile))==.8
