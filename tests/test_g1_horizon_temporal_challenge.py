import sqlite3,threading,json
from types import SimpleNamespace
from strategies.relative_value_lab.g0_forecast_challenge import challenge_forecast
from strategies.relative_value_lab.g0_live_evidence import horizon_from_feature,temporal_from_store
from strategies.volatility_breakout.models import FeatureVector,Forecast

def fv(values):
 return FeatureVector("BTC/USD",1700000000000,100,0.01,0.01,1.2,1.0,None,None,.2,2.0,1000000,
  100000000,.01,0,1,1,values=values,complete=True,return_zscore=2,trend_slope=.001,
  momentum_consistency=.8,atr_pct=.01)
def fc():
 return Forecast("BTC/USD",1700000000000,60,direction="UP",probability_positive_net=.6,
  expected_move_bps=20,expected_cost_bps=5,expected_net_bps=15,abstain=False,
  model_id="m",hypothesis="breakout_continuation")

def test_horizon_challenge_preserves_aligned_and_vetoes_blind():
 full=fv({"synthesis_context":{"families":("HORIZON",),"family_payloads":{
  "HORIZON":({"alignment":"ALIGNED_UP"},)}}})
 blind=fv({"synthesis_context":{"families":(),"family_payloads":{}}})
 assert not challenge_forecast(fc(),full,organ_scope="horizon_context").abstain
 assert challenge_forecast(fc(),blind,organ_scope="horizon_context").abstain

def test_temporal_challenge_requires_real_normal_or_elevated_participation():
 full=fv({"synthesis_context":{"families":("TEMPORAL_PARTICIPATION",),"family_payloads":{
  "TEMPORAL_PARTICIPATION":({"activity_state":"PARTICIPATION_ELEVATED"},)}}})
 blind=fv({"synthesis_context":{"families":(),"family_payloads":{}}})
 assert not challenge_forecast(fc(),full,organ_scope="temporal_participation_bee").abstain
 assert challenge_forecast(fc(),blind,organ_scope="temporal_participation_bee").abstain

def test_horizon_builder_uses_observed_worker_series_and_oracle_only():
 x=fv({"worker_series":{"closes":[90+i for i in range(70)],"volumes":[100+i for i in range(70)]},
       "cex_market_oracle":{"horizons":{"1h":{"change_bps":12.0},"24h":{"change_bps":25.0}}}})
 h=horizon_from_feature(x)
 assert h is not None and h.readiness["micro"] is False and h.readiness["macro_1h"] is True

def test_temporal_builder_uses_prior_snapshot_candle_volumes():
 class S:
  def __init__(self):
   self.conn=sqlite3.connect(":memory:");self._lock=threading.RLock()
   self.conn.execute("CREATE TABLE observation_snapshots(ts REAL,symbol TEXT,payload TEXT)")
 s=S();base=1700000000
 for d in range(7):
  ts=base-(d+1)*86400
  payload={"values":{"feature_vector":{"values":{"worker_series":{"volumes":[10,20,30]}}}}}
  s.conn.execute("INSERT INTO observation_snapshots VALUES(?,?,?)",(ts,"BTC/USD",json.dumps(payload)))
 s.conn.commit()
 x=fv({"worker_series":{"volumes":[10,20,60]}})
 e=temporal_from_store(s,x)
 assert e is not None and e.execution_eligible is False
