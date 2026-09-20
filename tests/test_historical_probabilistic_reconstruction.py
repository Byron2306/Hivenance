import sqlite3

import pytest

from strategies.relative_value_lab.historical_probabilistic_reconstruction import (
    HistoricalBayesianRegimeReconstructor,
    HistoricalStatisticsReconstructor,
    deterministic_regime_likelihoods,
)
from strategies.volatility_breakout.models import FeatureVector


def feature(*, timestamp_ms=1000, hint="trend_expansion", confidence=.8):
    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=timestamp_ms,
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
        values={
            "regime_inputs":{
                "regime_hint":hint,
                "confidence":confidence,
            }
        },
        complete=True,
    )


def test_regime_likelihoods_follow_deterministic_hint():
    out=deterministic_regime_likelihoods({
        "regime_hint":"trend_expansion",
        "confidence":.8,
    })
    assert out["TREND"]>out["MEAN_REVERSION"]


def test_bayesian_reconstruction_never_uses_same_timestamp():
    r=HistoricalBayesianRegimeReconstructor()
    f1=feature(timestamp_ms=1000)
    c1=r.context_for(f1)
    r.stage(f1)

    same=feature(timestamp_ms=1000)
    c_same=r.context_for(same)
    assert c1.dominant_posterior_regime is None
    assert c_same.dominant_posterior_regime is None

    later=feature(timestamp_ms=2000)
    c2=r.context_for(later)
    assert c2.dominant_posterior_regime is not None
    assert c2.evidence_cutoff_ms==1000


def test_same_time_conflicting_regime_truth_is_refused():
    r=HistoricalBayesianRegimeReconstructor()
    r.stage(feature(timestamp_ms=1000,hint="trend_expansion"))
    with pytest.raises(ValueError,match="same_time_regime_conflict"):
        r.stage(feature(timestamp_ms=1000,hint="quiet_range"))


def test_statistics_reconstruction_respects_strict_settlement_cutoff():
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE hypothesis_forecasts(
            forecast_id TEXT,
            model_id TEXT,
            symbol TEXT,
            horizon_seconds INTEGER,
            ts REAL,
            payload TEXT,
            abstain INTEGER
        );
        CREATE TABLE hypothesis_outcomes(
            forecast_id TEXT,
            net_return_bps REAL,
            settled_ts REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO hypothesis_forecasts VALUES(?,?,?,?,?,?,?)",
        (
            "f1","m1","BTC/USD",60,1.0,
            '{"inputs":{"regime_hint":"trend_expansion"}}',
            0,
        ),
    )
    conn.execute(
        "INSERT INTO hypothesis_outcomes VALUES(?,?,?)",
        ("f1",5.0,2.0),
    )
    recon=HistoricalStatisticsReconstructor(conn)

    before=recon.states_for(
        feature(timestamp_ms=2000),
        model_ids=("m1",),
        horizon_seconds=60,
    )["m1"]
    after=recon.states_for(
        feature(timestamp_ms=2001),
        model_ids=("m1",),
        horizon_seconds=60,
    )["m1"]

    assert before.effective_sample_size==0.0
    assert after.effective_sample_size==1.0



def test_hierarchical_statistics_expand_depth_without_double_counting():
    conn=sqlite3.connect(":memory:")
    conn.row_factory=sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE hypothesis_forecasts(
            forecast_id TEXT,
            model_id TEXT,
            symbol TEXT,
            horizon_seconds INTEGER,
            ts REAL,
            payload TEXT,
            abstain INTEGER
        );
        CREATE TABLE hypothesis_outcomes(
            forecast_id TEXT,
            net_return_bps REAL,
            settled_ts REAL
        );
        """
    )
    rows=(
        ("f1","m1","BTC/USD",60,1.0,'{"inputs":{"regime_hint":"trend_expansion"}}',0,5.0,2.0),
        ("f2","m1","BTC/USD",60,2.0,'{"inputs":{"regime_hint":"quiet_range"}}',0,-2.0,3.0),
        ("f3","m1","ETH/USD",60,3.0,'{"inputs":{"regime_hint":"trend_expansion"}}',0,4.0,4.0),
        ("f4","m1","ETH/USD",60,4.0,'{"inputs":{"regime_hint":"quiet_range"}}',0,1.0,5.0),
    )
    for row in rows:
        conn.execute(
            "INSERT INTO hypothesis_forecasts VALUES(?,?,?,?,?,?,?)",
            row[:7],
        )
        conn.execute(
            "INSERT INTO hypothesis_outcomes VALUES(?,?,?)",
            (row[0],row[7],row[8]),
        )

    recon=HistoricalStatisticsReconstructor(conn)
    state=recon.states_for(
        feature(timestamp_ms=6000),
        model_ids=("m1",),
        horizon_seconds=60,
    )["m1"]

    assert state.effective_sample_size==4.0
    assert len(state.source_snapshot_ids)>=2
    assert state.contributing_scopes[0].startswith("exact|m1|BTC/USD|60|trend_expansion")
