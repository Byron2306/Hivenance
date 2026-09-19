import pytest
from types import SimpleNamespace
from strategies.relative_value_lab.g0_twin_freeze import freeze_shadow_twin

def intent(target):
 return {"target_ts":target,"transmission_status":"NEVER_TRANSMITTED","live_eligible":False,"execution_wired":False}

def test_twin_freeze_requires_future_identical_target_and_same_world():
 f=SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64)
 c=SimpleNamespace(world_state_hash=f.world_state_hash,cycle_id="c1")
 d=SimpleNamespace(world_state_hash=f.world_state_hash,cycle_id="c2")
 x=freeze_shadow_twin(organ_id="edge_ecology",opportunity_id="o",frame=f,full_cycle=c,ablated_cycle=d,
  full_cognition_hash="sha256:"+"b"*64,ablated_cognition_hash="sha256:"+"c"*64,
  full_intent=intent(20),ablated_intent=intent(20),frozen_at_ms=10000)
 assert x.target_ts==20 and not x.execution_eligible and not x.promotion_eligible

def test_twin_freeze_refuses_lookahead_or_mismatched_world():
 f=SimpleNamespace(world_state_id="w",world_state_hash="sha256:"+"a"*64)
 c=SimpleNamespace(world_state_hash=f.world_state_hash,cycle_id="c1")
 bad=SimpleNamespace(world_state_hash="sha256:"+"f"*64,cycle_id="c2")
 with pytest.raises(ValueError,match="share_frozen_world"):
  freeze_shadow_twin(organ_id="x",opportunity_id="o",frame=f,full_cycle=c,ablated_cycle=bad,
   full_cognition_hash="h",ablated_cognition_hash="b",full_intent=intent(20),ablated_intent=intent(20),frozen_at_ms=10000)
 with pytest.raises(ValueError,match="future"):
  freeze_shadow_twin(organ_id="x",opportunity_id="o",frame=f,full_cycle=c,ablated_cycle=c,
   full_cognition_hash="h",ablated_cognition_hash="b",full_intent=intent(10),ablated_intent=intent(10),frozen_at_ms=10000)
