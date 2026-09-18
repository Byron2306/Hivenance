from __future__ import annotations

from agents.horizon_context import AUTHORITY as HORIZON_AUTHORITY, HorizonContextAgent
from scripts.run_live_inventory_drizzle_lab import MUTATIONS, PairState


def test_inventory_mutations_include_hold_benchmark():
    assert MUTATIONS[0]=="inventory_hold"
    assert set(MUTATIONS)=={
        "inventory_hold",
        "inventory_naive",
        "inventory_band",
        "inventory_streak",
        "inventory_swarm_streak",
    }


def test_pair_relative_capture_turns_positive_after_rebound():
    pair=PairState()
    for ratio in (1.0000,0.9995,0.9990,0.9985,0.9980,0.9975,0.9970,0.9965,0.9960,0.9955):
        pair.ratios.append(ratio)
    assert pair.zscore(10)<0
    assert pair.drawdown_bps(10)<0
    prior=pair.ratios[-1]
    pair.ratios.append(prior*1.0015)
    assert pair.ret_bps(1)>0


def test_route_cost_math_requires_edge_above_cost():
    gross_capture_bps=12.0
    route_cost_bps=8.0
    assert gross_capture_bps-route_cost_bps==4.0
    assert (6.0-route_cost_bps)<0


def test_horizon_agent_is_research_only_and_builds_three_scales():
    assert "NO_EXECUTION_AUTHORITY" in HORIZON_AUTHORITY
    agent=HorizonContextAgent(deadband_bps=1.0)
    context=agent.build(
        symbol="SOL/USD",
        timestamp=1.0,
        returns_bps={
            "10s":2.0,"30s":3.0,"2m":5.0,"5m":7.0,"15m":9.0,"1h":12.0
        },
        realized_vol_bps={"30s":2.0,"5m":4.0},
        ticker_24h={"open":100.0,"last":102.0,"high":103.0,"low":98.0},
        cross_sectional_returns={
            "30s":[1.0,2.0,3.0],"2m":[2.0,4.0,5.0],"5m":[3.0,5.0,7.0],
            "15m":[4.0,7.0,9.0],"1h":[5.0,8.0,12.0],
        },
    ).to_dict()
    assert context["micro"]["bias"]=="UP"
    assert context["meso"]["bias"]=="UP"
    assert context["macro"]["bias"]=="UP"
    assert context["alignment"]=="ALIGNED_UP"
    assert context["readiness"]["macro_15m"] is True
    assert context["readiness"]["macro_1h"] is True


def test_inventory_source_has_no_private_execution_tokens():
    from pathlib import Path
    source=Path("scripts/run_live_inventory_drizzle_lab.py").read_text(encoding="utf-8")
    for token in (
        ".create_order(",
        ".fetch_balance(",
        "HIVENANCE_PHASE6_LIVE_SUBMISSION",
        "apiKey",
        "apiSecret",
        "private_key",
    ):
        assert token not in source


def test_horizon_source_has_no_private_execution_tokens():
    from pathlib import Path
    source=Path("scripts/run_hivenance_horizon_observer.py").read_text(encoding="utf-8")
    for token in (
        ".create_order(",
        ".fetch_balance(",
        "HIVENANCE_PHASE6_LIVE_SUBMISSION",
        "apiKey",
        "apiSecret",
        "private_key",
    ):
        assert token not in source
