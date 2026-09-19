from types import SimpleNamespace
from agents.coin_selector import CoinSelector

def cfg(**kw):
    base=dict(
        symbol_memory_path="/definitely/missing.json",
        promotion_allowed_stages=["paper","research_import"],
        core_assets=[],experimental_assets=[],
        coin_selection_min_vol_usd=100000,
        coin_selection_spread_max=0.03,
        coin_selection_target_volatility=0.006,
        coin_selection_max_volatility=0.025,
        volatility_harvest_enabled=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)

def test_temporal_profile_reports_only_available_history():
    selector=CoinSelector(cfg())
    closes=[100.0+i*0.1 for i in range(121)]
    p=selector._temporal_profile(closes,"1m")
    assert p["readiness"]["15m"] is True
    assert p["readiness"]["1h"] is True
    assert p["readiness"]["4h"] is False
    assert p["readiness"]["24h"] is False
    assert p["readiness"]["7d"] is False
    assert p["returns_bps"]["1h"] > 0
    assert p["coverage_minutes"] == 120

def test_temporal_context_is_visible_in_score_components():
    selector=CoinSelector(cfg())
    c={
        "symbol":"BTC/USD","quote_volume":5_000_000,
        "spread_pct":0.001,"volatility":0.006,
        "temporal_profile":{"directional_alignment":1.0,"trend_efficiency":1.0},
    }
    out=selector._score_candidate(c,{})
    assert out["score_components"]["temporal_context"] == 1.0
    assert out["temporal_profile"]["readiness"] if "readiness" in out["temporal_profile"] else True
