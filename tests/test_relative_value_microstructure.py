from __future__ import annotations

from strategies.relative_value_lab.microstructure import SequentialMicrostructureEngine


def _book(bid=100.0,ask=100.1,bid_size=5.0,ask_size=5.0):
    return {
        "bids":[[bid,bid_size],[bid*0.9995,8.0],[bid*0.998,10.0]],
        "asks":[[ask,ask_size],[ask*1.0005,8.0],[ask*1.002,10.0]],
    }


def test_microstructure_computes_spread_depth_and_trade_flow():
    engine=SequentialMicrostructureEngine()
    snap=engine.build(
        symbol="SOL/USD",
        timestamp_ms=1,
        orderbook=_book(),
        trades=[
            {"price":100.1,"amount":2.0,"side":"buy"},
            {"price":100.0,"amount":1.0,"side":"sell"},
        ],
        observation_window_sec=1.0,
    )
    assert snap.spread_bps is not None and snap.spread_bps>0
    assert snap.bid_depth_usd_25bps is not None and snap.bid_depth_usd_25bps>0
    assert snap.ask_depth_usd_25bps is not None and snap.ask_depth_usd_25bps>0
    assert snap.aggressor_flow_imbalance is not None
    assert snap.aggressor_flow_imbalance>0
    assert snap.trade_count==2
    assert snap.trade_intensity_per_sec==2.0
    assert snap.execution_eligible is False


def test_quote_ofi_requires_sequential_book():
    engine=SequentialMicrostructureEngine()
    first=engine.build(symbol="SOL/USD",timestamp_ms=1,orderbook=_book())
    second=engine.build(
        symbol="SOL/USD",
        timestamp_ms=2,
        orderbook=_book(bid=100.0,ask=100.1,bid_size=8.0,ask_size=3.0),
    )
    assert first.quote_ofi_proxy is None
    assert second.quote_ofi_proxy is not None
    assert second.quote_ofi_proxy>0


def test_depth_recovery_is_sequential_and_observational():
    engine=SequentialMicrostructureEngine()
    first=engine.build(symbol="SOL/USD",timestamp_ms=1,orderbook=_book(bid_size=2.0,ask_size=2.0))
    second=engine.build(symbol="SOL/USD",timestamp_ms=2,orderbook=_book(bid_size=8.0,ask_size=8.0))
    assert first.depth_recovery_score is None
    assert second.depth_recovery_score is not None
    assert second.depth_recovery_score>0
    assert second.authority.endswith("no_execution_or_promotion_authority")
