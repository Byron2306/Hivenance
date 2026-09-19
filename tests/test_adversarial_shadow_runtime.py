from dataclasses import asdict
from strategies.volatility_breakout.adversarial_shadow_runtime import prosecute_settled_shadow
from strategies.volatility_breakout.shadow_models import ShadowOrderIntent
from strategies.volatility_breakout.shadow_flight import ShadowSettlementEngine

class Store:
 def __init__(self): self.rows=[]
 def persist_phase5_adversarial_shadow_receipt(self,r): self.rows.append(r); return True
class Cfg:
 phase5_shadow_entry_latency_sec=1;phase5_shadow_fee_bps=1;phase5_shadow_impact_bps=1
 phase5_shadow_min_data_quality=0;phase5_shadow_max_spread_bps=1000;phase5_shadow_min_depth_usd=0
 phase5_shadow_chase_timeout_sec=1;phase5_shadow_chase_slippage_bps=1

def _i():
 return ShadowOrderIntent("s","f","z","p","c","m","market","kraken","BTC/USD","UP","buy","market","IOC",1,100,100,None,10,1,100,2,98,.6,60,999,1060,1,2,10000,"v","h")

def test_runtime_court_uses_canonical_store_and_keeps_authority_closed():
 st=Store(); tape=[{"ts":1000,"price":100,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1060,"price":110,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1120,"price":90,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1180,"price":80,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1}]
 r=prosecute_settled_shadow(data_store=st,settler=ShadowSettlementEngine(Cfg()),intent_row={"payload":__import__("json").dumps(asdict(_i()))},observations=tape,settled_ts=1181)
 assert r["created"] and len(st.rows)==1
 x=st.rows[0]
 assert x["authority"]=="PROSPECTIVE_SHADOW_RESEARCH_ONLY"
 assert not x["execution_eligible"] and not x["promotion_eligible"]
 assert x["learning"]["comparisons"]["candidate_minus_no_trade_bps"]>0
