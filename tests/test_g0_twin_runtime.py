import sqlite3
from types import SimpleNamespace
from strategies.relative_value_lab.g0_twin_store import persist_frozen_twin,mature_frozen_twins
from strategies.relative_value_lab.g0_twin_runtime import settle_mature_g0_twins

class Store:
 def __init__(self):
  self.conn=sqlite3.connect(":memory:");import threading;self._lock=threading.RLock()
  self.conn.execute("CREATE TABLE observation_snapshots(symbol TEXT,ts REAL,payload TEXT)")
  self.conn.execute("INSERT INTO observation_snapshots VALUES('BTC/USD',11,'{}')")
  self.conn.execute("INSERT INTO observation_snapshots VALUES('BTC/USD',20,'{}')")
class Settler:
 def settle(self,intent,observations,settled_ts):
  class X:
   def __init__(self,v):self.v=v
   def to_dict(self):return {"status":"SETTLED","net_return_bps":self.v}
  return X(float(intent["score"]))
def frozen():
 return SimpleNamespace(to_dict=lambda:{"twin_freeze_id":"t1","organ_id":"edge_ecology","opportunity_id":"o1",
  "world_state_hash":"sha256:"+"a"*64,"frozen_at_ms":10000,"target_ts":20.0,
  "full_intent":{"symbol":"BTC/USD","created_ts":10,"target_ts":20,"score":3,"transmission_status":"NEVER_TRANSMITTED","live_eligible":False,"execution_wired":False},
  "ablated_intent":{"symbol":"BTC/USD","created_ts":10,"target_ts":20,"score":1,"transmission_status":"NEVER_TRANSMITTED","live_eligible":False,"execution_wired":False},
  "authority":"SYNTHESIS_G0_PROSPECTIVE_SHADOW_ONLY","execution_eligible":False,"promotion_eligible":False})
def test_persist_then_mature_then_settle_from_canonical_tape():
 s=Store();assert persist_frozen_twin(s,frozen());assert len(mature_frozen_twins(s,now_ts=19))==0
 r=settle_mature_g0_twins(s,Settler(),now_ts=21,tolerance_sec=5)
 assert r=={"examined":1,"settled":1,"errors":0}
 assert len(mature_frozen_twins(s,now_ts=30))==0
 row=s.conn.execute("SELECT payload FROM phase5_g0_shadow_twin_settlements").fetchone()[0]
 import json;p=json.loads(row);assert p["paired_outcome"]["delta_bps"]==2
 assert p["execution_eligible"] is False and p["promotion_eligible"] is False
