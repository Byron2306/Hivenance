import json,sqlite3,threading
from types import SimpleNamespace
from strategies.relative_value_lab.g0_live_loop import G0LiveLoop
from strategies.relative_value_lab.g0_twin_runtime import settle_mature_g0_twins
from strategies.volatility_breakout.models import FeatureVector,Forecast

class Store:
 def __init__(self):
  self.conn=sqlite3.connect(":memory:");self._lock=threading.RLock()
  self.conn.execute("CREATE TABLE observation_snapshots(symbol TEXT,ts REAL,payload TEXT)")
 def get_phase5_active_freeze(self):
  return {"freeze_id":"z","phase4_run_id":"p4","candidate_key":"k","model_id":"m","order_policy":"market",
   "approved_by":"human","approved_ts":1.0,"phase4_dataset_hash":"d","config_hash":"c",
   "symbol":"BTC/USD","direction":"UP","status":"ACTIVE"}

class Competition:
 def evaluate(self,feature,horizons):
  return [Forecast("BTC/USD",10000,60,direction="UP",probability_positive_net=.6,
   expected_move_bps=20,expected_cost_bps=5,expected_net_bps=15,abstain=False,
   model_id="m",hypothesis="breakout_continuation",execution_eligible=False)]

class Builder:
 def build(self,f,o,z):
  return SimpleNamespace(to_dict=lambda:{"shadow_intent_id":"full","forecast_id":f["forecast_id"],
   "symbol":f["symbol"],"direction":f["direction"],"created_ts":f["ts"],"target_ts":f["target_ts"],
   "transmission_status":"NEVER_TRANSMITTED","live_eligible":False,"execution_wired":False,
   "execution_eligible":False,"promotion_eligible":False})

class Settlement:
 def to_dict(self):return {"status":"SETTLED","net_return_bps":3.0}
class Settler:
 def settle(self,intent,observations,settled_ts):return Settlement()

def feature():
 return FeatureVector("BTC/USD",10000,100,0.01,0.01,1.2,1.0,None,None,.2,2.0,1000000,
  100000000,.01,0,1,1,values={},complete=True,return_zscore=2,trend_slope=.001,
  momentum_consistency=.8,atr_pct=.01)

def test_autonomous_g0_birth_to_future_settlement():
 s=Store();cfg=SimpleNamespace(exchange="kraken",phase1_observation_stale_after_sec=180)
 loop=G0LiveLoop(cfg);loop.builder=Builder()
 born=loop.process_feature(data_store=s,competition=Competition(),feature=feature(),venue="kraken",
  now_ms=10000,horizons=(60,))
 assert born["frozen"]>=1
 assert born["by_organ"]["edge_ecology"]["diverged"]==0
 s.conn.execute("INSERT INTO observation_snapshots VALUES(?,?,?)",("BTC/USD",70.0,json.dumps({"price":103})))
 s.conn.commit()
 settled=settle_mature_g0_twins(s,Settler(),now_ts=71.0,tolerance_sec=5)
 assert settled["examined"]>=1 and settled["settled"]>=1 and settled["errors"]==0
 payloads=[json.loads(row[0]) for row in s.conn.execute("SELECT payload FROM phase5_g0_shadow_twin_settlements").fetchall()]
 assert all(p["paired_outcome"]["delta_bps"] in {3.0,-3.0} for p in payloads)
 assert any(
  p["paired_outcome"]["full_acted"] is False and p["paired_outcome"]["ablated_acted"] is True
  for p in payloads
 )
 assert any(p["full_settlement"]["status"]=="ABSTAIN_NO_TRADE" for p in payloads)
 assert all(not p["execution_eligible"] and not p["promotion_eligible"] for p in payloads)
