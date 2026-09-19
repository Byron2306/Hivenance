import sqlite3,threading
from types import SimpleNamespace
from strategies.relative_value_lab.g0_live_loop import G0LiveLoop
from strategies.volatility_breakout.models import FeatureVector,Forecast

class Store:
 def __init__(self):self.conn=sqlite3.connect(":memory:");self._lock=threading.RLock()
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

def feature():
 return FeatureVector("BTC/USD",10000,100,0.01,0.01,1.2,1.0,None,None,.2,2.0,1000000,
  100000000,.01,0,1,1,values={},complete=True,return_zscore=2,trend_slope=.001,
  momentum_consistency=.8,atr_pct=.01)

def test_live_loop_freezes_trade_vs_edge_blind_abstain_before_outcome():
 cfg=SimpleNamespace(exchange="kraken",phase1_observation_stale_after_sec=180)
 loop=G0LiveLoop(cfg);loop.builder=Builder();s=Store()
 r=loop.process_feature(data_store=s,competition=Competition(),feature=feature(),venue="kraken",
  now_ms=10000,horizons=(60,))
 assert r["diverged"]==1 and r["frozen"]==1 and r["errors"]==0
 row=s.conn.execute("SELECT status,payload FROM phase5_g0_shadow_twins").fetchone()
 assert row[0]=="FROZEN"
 assert '"g0_no_trade":true' in row[1]
