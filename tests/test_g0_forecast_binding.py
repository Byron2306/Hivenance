import sqlite3,threading,pytest
from types import SimpleNamespace
from strategies.relative_value_lab.g0_forecast_binding import freeze_forecast_pair
class Store:
 def __init__(self):self.conn=sqlite3.connect(":memory:");self._lock=threading.RLock()
class Builder:
 def build(self,f,o,z):
  return SimpleNamespace(to_dict=lambda:{"symbol":f["symbol"],"target_ts":f["target_ts"],"created_ts":f["ts"],
   "direction":f["direction"],"transmission_status":"NEVER_TRANSMITTED","live_eligible":False,"execution_wired":False})
def cyc(i,fams):
 return SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64,cycle_id=i,
  queen_view=SimpleNamespace(families=fams),learning={},attention_obligations=(),organ_requests=())
def fc(d="UP",sym="BTC/USD",h=10):
 return {"symbol":sym,"model_id":"m","direction":d,"horizon_seconds":h,"ts":10.0,"target_ts":20.0,"abstain":False}
def test_real_forecasts_flow_through_existing_builder_then_freeze():
 s=Store();frame=SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64)
 r=freeze_forecast_pair(data_store=s,builder=Builder(),freeze=object(),organ_id="edge_ecology",opportunity_id="o",
  frame=frame,full_cycle=cyc("f",("FLOW",)),ablated_cycle=cyc("b",()),full_forecast=fc("UP"),
  ablated_forecast=fc("DOWN"),full_observation={},ablated_observation={},frozen_at_ms=10000)
 assert r["created"] and not r["execution_eligible"]
def test_refuses_unpaired_horizons():
 s=Store();frame=SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64)
 with pytest.raises(ValueError,match="horizon"):
  freeze_forecast_pair(data_store=s,builder=Builder(),freeze=object(),organ_id="edge_ecology",opportunity_id="o",
   frame=frame,full_cycle=cyc("f",("FLOW",)),ablated_cycle=cyc("b",()),full_forecast=fc(h=10),
   ablated_forecast=fc(h=20),full_observation={},ablated_observation={},frozen_at_ms=10000)
