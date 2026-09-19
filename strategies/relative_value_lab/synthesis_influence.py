"""Causal influence accounting for same-world synthesis ablations."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass
from typing import Any,Mapping

def _canon(v:Any)->str:
 return json.dumps(v,sort_keys=True,separators=(",",":"),default=str)
def _hash(v:Any)->str:
 return "sha256:"+hashlib.sha256(_canon(v).encode()).hexdigest()

@dataclass(frozen=True)
class InfluenceReceipt:
 organ_id:str
 world_state_id:str
 world_state_hash:str
 full_cycle_id:str
 ablated_cycle_id:str
 cognition_changed:bool
 changed_families:tuple[str,...]
 changed_obligations:bool
 changed_requests:bool
 full_cognition_hash:str
 ablated_cognition_hash:str
 execution_eligible:bool=False
 promotion_eligible:bool=False
 def to_dict(self)->dict[str,Any]: return asdict(self)

def _surface(cycle:Any)->Mapping[str,Any]:
 return {
  "families":tuple(cycle.queen_view.families),
  "learning":cycle.learning,
  "attention_obligations":cycle.attention_obligations,
  "organ_requests":cycle.organ_requests,
 }

def measure_influence(*,organ_id:str,full:Any,ablated:Any)->InfluenceReceipt:
 if full.world_state_id!=ablated.world_state_id or full.world_state_hash!=ablated.world_state_hash:
  raise ValueError("influence_requires_identical_world")
 a=_surface(full);b=_surface(ablated)
 af=set(a["families"]);bf=set(b["families"])
 return InfluenceReceipt(
  organ_id=str(organ_id),world_state_id=full.world_state_id,world_state_hash=full.world_state_hash,
  full_cycle_id=full.cycle_id,ablated_cycle_id=ablated.cycle_id,
  cognition_changed=_canon(a)!=_canon(b),
  changed_families=tuple(sorted(af.symmetric_difference(bf))),
  changed_obligations=_canon(a["attention_obligations"])!=_canon(b["attention_obligations"]),
  changed_requests=_canon(a["organ_requests"])!=_canon(b["organ_requests"]),
  full_cognition_hash=_hash(a),ablated_cognition_hash=_hash(b),
  execution_eligible=False,promotion_eligible=False)
