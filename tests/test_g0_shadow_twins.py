import pytest
from strategies.relative_value_lab.g0_shadow_twins import G0ShadowTwin,settle_shadow_twin

class S:
 def settle(self,intent,obs,settled_ts):
  class X:
   def __init__(self,d):self.d=d
   def to_dict(self):return self.d
  return X({"status":"SETTLED","net_return_bps":float(intent["score"])})

def intent(score):
 return {"score":score,"transmission_status":"NEVER_TRANSMITTED","live_eligible":False,"execution_wired":False}

def test_twins_settle_on_one_shared_tape_and_emit_prospective_pair():
 t=G0ShadowTwin("edge_ecology","opp1","sha256:"+"a"*64,intent(4),intent(1))
 x=settle_shadow_twin(twin=t,settler=S(),observations=({"ts":1},),settled_ts=2)
 assert x.paired_outcome.evidence_class=="PROSPECTIVE"
 assert x.paired_outcome.delta_bps==3
 assert not x.execution_eligible and not x.promotion_eligible

def test_twins_refuse_missing_tape_or_execution_authority():
 t=G0ShadowTwin("x","o","sha256:"+"a"*64,intent(1),intent(0))
 with pytest.raises(ValueError,match="shared_future"):settle_shadow_twin(twin=t,settler=S(),observations=(),settled_ts=2)
 bad=intent(1);bad["live_eligible"]=True
 t=G0ShadowTwin("x","o","sha256:"+"a"*64,bad,intent(0))
 with pytest.raises(ValueError,match="authority"):settle_shadow_twin(twin=t,settler=S(),observations=({"ts":1},),settled_ts=2)
