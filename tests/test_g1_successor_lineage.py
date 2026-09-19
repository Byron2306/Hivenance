import json,sqlite3,threading
from dataclasses import replace
from types import SimpleNamespace

from strategies.relative_value_lab.g1_campaign_freeze import (
 freeze_g1_campaign,freeze_g1_campaign_successor,get_latest_g1_campaign_freeze,
 policy_from_freeze,
)
from strategies.relative_value_lab.g1_research_target import (
 freeze_g1_research_target_successor,PRIMARY_MODEL_IDS,
)
from strategies.relative_value_lab.g1_utility_campaign import G1CampaignPolicy,load_prospective_outcomes

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

def test_successor_preserves_predecessor_and_freezes_primary_roster():
 s=Store();organs=("edge_ecology","horizon_context")
 first=freeze_g1_campaign(s,policy=G1CampaignPolicy(),organs=organs,created_ts=1.0)
 target=freeze_g1_research_target_successor(
  s,cfg(),model_ids=PRIMARY_MODEL_IDS,predecessor_target_id="legacy",created_ts=2.0)
 policy=replace(policy_from_freeze(first),confidence_z=2.690)
 second=freeze_g1_campaign_successor(
  s,policy=policy,organs=organs,research_target_id=target["target_id"],
  predecessor_campaign_id=first["campaign_id"],created_ts=3.0)
 assert second["campaign_id"]!=first["campaign_id"]
 assert second["predecessor_campaign_id"]==first["campaign_id"]
 assert second["research_target_id"]==target["target_id"]
 assert tuple(target["model_ids"])==PRIMARY_MODEL_IDS
 assert get_latest_g1_campaign_freeze(s)["campaign_id"]==second["campaign_id"]
 assert s.conn.execute("SELECT COUNT(*) FROM g1_campaign_freeze").fetchone()[0]==2

def test_outcomes_are_filtered_by_campaign_and_target():
 s=Store()
 s.conn.execute("""CREATE TABLE phase5_g0_shadow_twin_settlements(
  twin_freeze_id TEXT PRIMARY KEY,settled_ts REAL NOT NULL,payload_sha256 TEXT NOT NULL,
  authority TEXT NOT NULL,execution_eligible INTEGER NOT NULL DEFAULT 0,
  promotion_eligible INTEGER NOT NULL DEFAULT 0,payload TEXT NOT NULL)""")
 def add(tid,campaign,target,delta):
  pair={"organ_id":"edge_ecology","evidence_class":"PROSPECTIVE","opportunity_id":tid,
   "world_state_hash":"sha256:"+"a"*64,"full_net_bps":delta,"ablated_net_bps":0.0,
   "delta_bps":delta,"full_acted":True,"ablated_acted":True,
   "research_campaign_id":campaign,"research_target_id":target,
   "execution_eligible":False,"promotion_eligible":False}
  payload=json.dumps({"paired_outcome":pair})
  s.conn.execute("INSERT INTO phase5_g0_shadow_twin_settlements VALUES(?,?,?,?,?,?,?)",
   (tid,1.0,"sha","SYNTHESIS_G0_PROSPECTIVE_SHADOW_ONLY",0,0,payload))
 add("a","c1","t1",1.0);add("b","c2","t2",2.0);s.conn.commit()
 rows=load_prospective_outcomes(s,campaign_id="c2",target_id="t2")
 assert len(rows)==1 and rows[0]["delta_bps"]==2.0
