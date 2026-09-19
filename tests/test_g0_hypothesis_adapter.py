from dataclasses import replace
from types import SimpleNamespace
from strategies.relative_value_lab.g0_hypothesis_adapter import bind_synthesis_context,evaluate_synthesis_pair
from strategies.volatility_breakout.models import FeatureVector

def feature():
 return FeatureVector(symbol="BTC/USD",timestamp_ms=10,price=100,
  realized_volatility_fast=None,realized_volatility_baseline=None,volatility_expansion=None,
  volume_zscore=None,trade_count_zscore=None,order_flow_imbalance=None,book_imbalance=None,
  spread_bps=None,depth_usd_25bps=None,quote_volume_24h=None,return_5=None,freshness_sec=None,
  continuity_ratio=None,data_quality=1.0,values={})
def cyc(i,f):
 return SimpleNamespace(cycle_id=i,world_state_id="w",world_state_hash="sha256:"+"a"*64,
  queen_view=SimpleNamespace(families=f),learning={},attention_obligations=(),organ_requests=())
class Competition:
 def evaluate(self,x,h):
  c=x.values["synthesis_context"];return [{"direction":"UP" if "FLOW" in c["families"] else "DOWN",
   "context_cycle":c["cycle_id"],"execution_eligible":False}]
def test_same_phoenix_competition_sees_independent_synthesis_contexts():
 r=evaluate_synthesis_pair(competition=Competition(),feature=feature(),horizons=(10,),
  full_cycle=cyc("full",("FLOW",)),ablated_cycle=cyc("blind",()))
 assert r["full_forecasts"][0]["direction"]=="UP"
 assert r["ablated_forecasts"][0]["direction"]=="DOWN"
 assert not r["execution_eligible"]
def test_adapter_never_injects_forecast_semantics():
 x=bind_synthesis_context(feature(),cyc("full",("FLOW",)))
 c=x.values["synthesis_context"]
 assert "direction" not in c and "probability_positive_net" not in c and "expected_net_bps" not in c
 assert c["authority"]=="RESEARCH_CONTEXT_ONLY"
