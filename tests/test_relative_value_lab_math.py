from __future__ import annotations

import math

from strategies.relative_value_lab.microstructure import SequentialMicrostructureEngine
from strategies.relative_value_lab.pair_graph import RelativeValueGraph
from strategies.relative_value_lab.pair_lab import PairRelationshipLab


def test_microstructure_engine_computes_spread_depth_flow_and_warms_ofi():
    engine = SequentialMicrostructureEngine()
    book1 = {
        "bids": [[99.9, 2.0], [99.8, 3.0]],
        "asks": [[100.1, 1.5], [100.2, 2.5]],
    }
    trades1 = [
        {"price": 100.0, "amount": 1.0, "side": "buy"},
        {"price": 100.0, "amount": 0.5, "side": "sell"},
    ]
    first = engine.build(
        symbol="TEST/USD",
        timestamp_ms=1_000,
        orderbook=book1,
        trades=trades1,
        observation_window_sec=1.0,
    )
    assert first.mid == 100.0
    assert first.spread_bps is not None and 19.9 < first.spread_bps < 20.1
    assert first.bid_depth_usd_25bps is not None
    assert first.ask_depth_usd_25bps is not None
    assert first.aggressor_flow_imbalance is not None
    assert first.aggressor_flow_imbalance > 0
    assert first.quote_ofi_proxy is None
    assert "quote_ofi_warming" in first.source_notes
    assert first.execution_eligible is False

    book2 = {
        "bids": [[99.95, 2.5], [99.85, 3.0]],
        "asks": [[100.10, 1.0], [100.20, 2.0]],
    }
    second = engine.build(
        symbol="TEST/USD",
        timestamp_ms=2_000,
        orderbook=book2,
        trades=trades1,
        observation_window_sec=1.0,
    )
    assert second.quote_ofi_proxy is not None
    assert -1.0 <= second.quote_ofi_proxy <= 1.0
    assert second.depth_recovery_score is not None
    assert second.data_quality == 1.0


def _synthetic_pair(samples: int = 240) -> tuple[list[float], list[float]]:
    base = []
    hedge = []
    spread = 0.015
    for i in range(samples):
        # Shared stochastic-like trend without randomness, plus a bounded
        # mean-reverting spread disturbance.
        b = 100.0 * math.exp(0.00035 * i + 0.002 * math.sin(i / 13.0))
        shock = 0.0018 * math.sin(i / 5.0) + 0.0006 * math.sin(i / 17.0)
        spread = 0.82 * spread + shock
        a = math.exp(0.2 + 1.03 * math.log(b) + spread)
        base.append(a)
        hedge.append(b)
    return base, hedge


def test_pair_lab_estimates_bounded_relationship_without_execution_authority():
    a, b = _synthetic_pair()
    lab = PairRelationshipLab(
        min_samples=100,
        min_return_correlation=0.0,
        min_stability_score=0.0,
        max_structural_break_score=20.0,
    )
    diagnostics, crystal = lab.analyze(
        symbol_a="A/USD",
        symbol_b="B/USD",
        prices_a=a,
        prices_b=b,
        sample_interval_sec=1.0,
        venue="test",
        observed_at_ms=123,
        direct_route_available=True,
    )

    assert diagnostics.samples == len(a)
    assert diagnostics.hedge_ratio is not None and diagnostics.hedge_ratio > 0
    assert diagnostics.ar1_phi is not None and 0 < diagnostics.ar1_phi < 1
    assert diagnostics.half_life_seconds is not None and diagnostics.half_life_seconds > 0
    assert diagnostics.spread_zscore is not None
    assert crystal.execution_eligible is False
    assert crystal.direct_route_available is True
    assert crystal.evidence_root and crystal.evidence_root.startswith("sha256:")


def test_pair_graph_creates_unique_edges_for_basket():
    a, b = _synthetic_pair(180)
    c = [price * math.exp(0.001 * math.sin(i / 7.0)) for i, price in enumerate(b)]
    graph = RelativeValueGraph(
        PairRelationshipLab(
            min_samples=60,
            min_return_correlation=0.0,
            min_stability_score=0.0,
            max_structural_break_score=20.0,
        )
    )
    edges, crystals, diagnostics = graph.analyze_basket(
        prices={"A/USD": a, "B/USD": b, "C/USD": c},
        sample_interval_sec=1.0,
        venue="test",
    )
    assert len(edges) == 3
    assert len(crystals) == 3
    assert len(diagnostics) == 3
    assert len({edge.pair_id for edge in edges}) == 3
