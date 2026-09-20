import pytest

from strategies.relative_value_lab.statistics_feedback_bridge import (
    hypothesis_scope,
    statistical_evidence_from_historical_outcome,
    statistical_evidence_from_settlement,
)


def test_settlement_becomes_point_in_time_statistical_evidence():
    settlement={
        "forecast_id":"f1",
        "pair_id":"BTC/USD__ETH/USD",
        "model_id":"m1",
        "forecast_timestamp_ms":100,
        "settled_timestamp_ms":200,
        "horizon_seconds":10,
        "realized_directional_net_bps":7.5,
        "abstain":False,
    }
    row=statistical_evidence_from_settlement(settlement,regime="TREND")
    assert row is not None
    assert row.available_at_ms==200
    assert row.observed_at_ms==100
    assert row.realized_bps==7.5
    assert row.positive is True
    assert row.scope==hypothesis_scope(
        model_id="m1",
        symbol="BTC/USD__ETH/USD",
        horizon_seconds=10,
        regime="TREND",
    )


def test_abstention_does_not_pollute_performance_memory():
    settlement={
        "forecast_id":"f1",
        "pair_id":"BTC/USD__ETH/USD",
        "model_id":"m1",
        "forecast_timestamp_ms":100,
        "settled_timestamp_ms":200,
        "horizon_seconds":10,
        "realized_directional_net_bps":0.0,
        "abstain":True,
    }
    assert statistical_evidence_from_settlement(settlement) is None


def test_feedback_refuses_nonfuture_settlement():
    with pytest.raises(ValueError,match="settlement_not_future"):
        statistical_evidence_from_settlement({
            "forecast_id":"f1",
            "pair_id":"BTC",
            "model_id":"m",
            "forecast_timestamp_ms":100,
            "settled_timestamp_ms":100,
            "horizon_seconds":10,
            "realized_directional_net_bps":1.0,
            "abstain":False,
        })


def test_historical_outcome_adapter_preserves_temporal_boundary():
    outcome={
        "symbol":"BTC/USD",
        "timestamp_ms":100,
        "horizon_seconds":60,
        "realized_net_bps":-4.0,
        "abstain":False,
    }
    row=statistical_evidence_from_historical_outcome(
        outcome,
        model_id="historical-model",
        settled_at_ms=200,
        regime="TRANSITION",
    )
    assert row.realized_bps==-4.0
    assert row.positive is False
    assert row.available_at_ms==200
