import sqlite3,threading
from types import SimpleNamespace
from strategies.relative_value_lab.g1_research_target import ensure_g1_research_target,shadow_freeze_from_research_target

class Store:
 def __init__(self):
  self.conn=sqlite3.connect(":memory:")
  self._lock=threading.RLock()

def cfg():
 return SimpleNamespace(
  exchange="kraken",phase2_horizons_seconds=[300,900,3600],phase2_min_data_quality=.99,
  phase2_minimum_edge_multiple=2.0,phase2_federation_enabled=False,phase2_federation_min_data_quality=.99,
  phase2_federation_minimum_edge_multiple=2.0,phase2_federation_score_scale=1.0,
  phase2_federation_freqai_confidence_floor=.5,phase2_breakout_min_expansion=1.25,
  phase2_breakout_min_volume_zscore=.5,phase2_breakout_min_return_zscore=.75,
  phase2_reversion_min_stretch_zscore=1.5,phase2_reversion_min_range_extreme=.85,
  phase3_simulated_equity_usd=1000.0,phase3_risk_fraction=.0005,phase3_sleeve_fraction=.02,
  phase3_max_notional_usd=25.0,phase3_max_depth_participation=.01,phase3_min_notional_usd=5.0,
  phase3_maker_fee_bps=10.0,phase3_taker_fee_bps=20.0,phase3_max_entry_spread_bps=60.0,
  phase5_shadow_reference_notional_usd=10.0,phase5_shadow_stop_distance_bps=250.0,
  phase5_shadow_max_intents_per_cycle=25,phase5_shadow_chase_timeout_sec=30,
  phase5_shadow_entry_latency_ms=250.0)

def test_research_target_is_immutable_non_authoritative_and_phase5_independent():
 s=Store();t1=ensure_g1_research_target(s,cfg(),created_ts=100.0);t2=ensure_g1_research_target(s,cfg(),created_ts=200.0)
 assert t1==t2
 assert t1["model_id"]=="breakout_continuation_v1"
 assert t1["order_policy"]=="market"
 assert t1["execution_eligible"] is False and t1["promotion_eligible"] is False and t1["transmission_eligible"] is False
 f=shadow_freeze_from_research_target(t1)
 assert f.phase4_run_id=="G1_RESEARCH_ONLY"
 assert f.approved_by=="G1_RESEARCH_PROTOCOL"
 assert f.execution_eligible is False and f.shadow_only is True
