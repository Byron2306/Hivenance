import sqlite3,threading,pytest
from types import SimpleNamespace
from strategies.relative_value_lab.g0_prospective_opportunity import freeze_prospective_opportunity

class Store:
 def __init__(self):self.conn=sqlite3.connect(":memory:");self._lock=threading.RLock()
class Q:families=("FLOW",)
class Q0:families=()
def cycle(i,q):
 return SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64,cycle_id=i,queen_view=q,
  learning={},attention_obligations=(),organ_requests=())
def intent(target):
 return {"target_ts":target,"created_ts":10,"symbol":"BTC/USD","transmission_status":"NEVER_TRANSMITTED",
  "live_eligible":False,"execution_wired":False}
def test_freezes_only_when_organ_changed_cognition_before_future_target():
 s=Store();f=SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64)
 r=freeze_prospective_opportunity(data_store=s,organ_id="edge_ecology",opportunity_id="o",frame=f,
  full_cycle=cycle("full",Q()),ablated_cycle=cycle("blind",Q0()),full_intent=intent(20),
  ablated_intent=intent(20),frozen_at_ms=10000)
 assert r["created"] and r["cognition_changed"] and not r["execution_eligible"]
 assert s.conn.execute("SELECT status FROM phase5_g0_shadow_twins").fetchone()[0]=="FROZEN"
def test_refuses_noncausal_twin():
 s=Store();f=SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64);c=cycle("x",Q())
 with pytest.raises(ValueError,match="did_not_change"):
  freeze_prospective_opportunity(data_store=s,organ_id="edge_ecology",opportunity_id="o",frame=f,
   full_cycle=c,ablated_cycle=c,full_intent=intent(20),ablated_intent=intent(20),frozen_at_ms=10000)
