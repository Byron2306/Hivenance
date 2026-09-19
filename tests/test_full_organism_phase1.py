from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from agents.market_memory import MarketMemory
from strategies.relative_value_lab.canonical_memory_bridge import (
    CanonicalMemoryWorldBridge,
    frame_from_binding,
    validate_binding,
    world_graph_root_from_binding,
)
from strategies.volatility_breakout.models import FeatureVector


def _rows(asof: int, n: int = 121):
    out = []
    for i in range(n):
        ts = asof - (n - 1 - i) * 60_000
        p = 100.0 + i * 0.1
        out.append([ts, p - 0.05, p + 0.10, p - 0.10, p, 10.0 + i])
    return out


def _feature(asof: int) -> FeatureVector:
    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=asof,
        price=112.0,
        realized_volatility_fast=0.01,
        realized_volatility_baseline=0.008,
        volatility_expansion=1.25,
        volume_zscore=0.5,
        trade_count_zscore=None,
        order_flow_imbalance=None,
        book_imbalance=0.2,
        spread_bps=2.0,
        depth_usd_25bps=500000.0,
        quote_volume_24h=100000000.0,
        return_5=0.002,
        freshness_sec=0.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        values={"regime_inputs": {"regime_hint": "balanced_transition", "confidence": 0.7}},
        complete=True,
        return_zscore=1.0,
        trend_slope=0.001,
        momentum_consistency=0.8,
        atr_pct=0.01,
    )


def _book():
    return {
        "bids": [[111.9, 100.0], [111.8, 80.0]],
        "asks": [[112.1, 90.0], [112.2, 70.0]],
    }


def test_phase1_bridge_is_idempotent_and_preserves_one_world_identity(tmp_path: Path):
    asof = 1_800_000_000_000
    db = tmp_path / "memory.db"
    bridge = CanonicalMemoryWorldBridge(db, freshness_window_ms=180000)
    payload = asdict(_feature(asof))

    first = bridge.ingest(
        venue="kraken", symbol="BTC/USD", observed_at_ms=asof,
        timeframe="1m", ohlcv=_rows(asof), orderbook=_book(),
        feature_payload=payload,
    )
    second = bridge.ingest(
        venue="kraken", symbol="BTC/USD", observed_at_ms=asof,
        timeframe="1m", ohlcv=_rows(asof), orderbook=_book(),
        feature_payload=payload,
    )

    assert first["canonical_world_state_id"] == second["canonical_world_state_id"]
    assert first["canonical_world_state_hash"] == second["canonical_world_state_hash"]
    assert first["feature_memory_line_id"] == second["feature_memory_line_id"]
    assert first["lineage_digest"] == second["lineage_digest"]
    assert first["world_state_page_status"] == "PRESENT"
    assert first["world_state_page"]["provenance"]["latest_1m_ts_ms"] <= asof
    assert validate_binding(first, symbol="BTC/USD", observed_at_ms=asof) == (True, ())

    memory = MarketMemory(db)
    try:
        assert len(memory.lines(kind="PHASE1_LIVE_FEATURE_OBSERVATION")) == 1
        assert len(memory.lines(kind="PUBLIC_ORDER_BOOK")) == 1
        assert len(memory.bars("BTC/USD", "1m")) == 121
    finally:
        memory.close()


def test_phase1_bridge_frame_is_live_observation_not_backfill_authority(tmp_path: Path):
    asof = 1_800_000_000_000
    db = tmp_path / "memory.db"
    memory = MarketMemory(db)
    try:
        memory.append_bars(
            symbol="BTC/USD", timeframe="1m", rows=_rows(asof - 60_000),
            source="kraken_public_ohlcv",
        )
    finally:
        memory.close()

    bridge = CanonicalMemoryWorldBridge(db)
    binding = bridge.ingest(
        venue="kraken", symbol="BTC/USD", observed_at_ms=asof,
        timeframe="1m", ohlcv=_rows(asof), orderbook=_book(),
        feature_payload=asdict(_feature(asof)),
    )
    frame = frame_from_binding(binding)

    assert frame.observation_count == 1
    assert frame.observations[0].source_class == "public_market_live_observation"
    assert frame.observations[0].source_id == "phase1_observation_swarm:kraken"
    assert binding["ingest_class"] == "LIVE_PROSPECTIVE_PUBLIC_OBSERVATION"
    assert frame.execution_eligible is False
    assert frame.promotion_eligible is False


def test_phase1_bridge_refuses_future_market_rows(tmp_path: Path):
    asof = 1_800_000_000_000
    rows = _rows(asof)
    rows.append([asof + 60_000, 1, 1, 1, 1, 1])
    bridge = CanonicalMemoryWorldBridge(tmp_path / "memory.db")

    with pytest.raises(ValueError, match="canonical_bridge_future_ohlcv_forbidden"):
        bridge.ingest(
            venue="kraken", symbol="BTC/USD", observed_at_ms=asof,
            timeframe="1m", ohlcv=rows, orderbook=_book(),
            feature_payload=asdict(_feature(asof)),
        )


def test_phase1_binding_round_trip_reproduces_canonical_frame(tmp_path: Path):
    asof = 1_800_000_000_000
    binding = CanonicalMemoryWorldBridge(tmp_path / "memory.db").ingest(
        venue="kraken", symbol="BTC/USD", observed_at_ms=asof,
        timeframe="1m", ohlcv=_rows(asof), orderbook=_book(),
        feature_payload=asdict(_feature(asof)),
    )
    frame = frame_from_binding(json.loads(json.dumps(binding)))
    assert frame.world_state_id == binding["canonical_world_state_id"]
    assert frame.world_state_hash == binding["canonical_world_state_hash"]
    assert frame.observations[0].evidence_root == binding["feature_memory_line_id"]


def test_phase1_world_state_page_binds_to_same_world_graph_root(tmp_path: Path):
    asof = 1_800_000_000_000
    binding = CanonicalMemoryWorldBridge(tmp_path / "memory.db").ingest(
        venue="kraken", symbol="BTC/USD", observed_at_ms=asof,
        timeframe="1m", ohlcv=_rows(asof), orderbook=_book(),
        feature_payload=asdict(_feature(asof)),
    )
    frame = frame_from_binding(binding)
    graph, node = world_graph_root_from_binding(binding)

    assert graph.frame.world_state_id == frame.world_state_id
    assert node.world_state_id == frame.world_state_id
    assert node.world_state_hash == frame.world_state_hash
    assert node.evidence_roots == (binding["feature_memory_line_id"],)
    assert node.family == "WORLD_STATE"
    assert node.execution_eligible is False
    assert node.promotion_eligible is False
