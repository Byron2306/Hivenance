"""Fail-closed pre-outcome freeze for prospective G0 shadow twins."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass
from typing import Any,Mapping

def _hash(v:Any)->str:
 return "sha256:"+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

@dataclass(frozen=True)
class FrozenG0Twin:
 twin_freeze_id:str; organ_id:str; opportunity_id:str; world_state_id:str; world_state_hash:str
 frozen_at_ms:int; target_ts:float; full_cycle_id:str; ablated_cycle_id:str
 full_cognition_hash:str; ablated_cognition_hash:str
 full_intent:Mapping[str,Any]; ablated_intent:Mapping[str,Any]
 research_campaign_id:str|None=None; research_target_id:str|None=None
 authority:str="SYNTHESIS_G0_PROSPECTIVE_SHADOW_ONLY"
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self):return asdict(self)

def freeze_shadow_twin(*,organ_id:str,opportunity_id:str,frame:Any,full_cycle:Any,
                       ablated_cycle:Any,full_cognition_hash:str,ablated_cognition_hash:str,
                       full_intent:Mapping[str,Any],ablated_intent:Mapping[str,Any],
                       frozen_at_ms:int,research_campaign_id:str|None=None,
                       research_target_id:str|None=None)->FrozenG0Twin:
 if full_cycle.world_state_hash!=frame.world_state_hash or ablated_cycle.world_state_hash!=frame.world_state_hash:
  raise ValueError("twin_cycles_must_share_frozen_world")
 targets={float(full_intent.get("target_ts") or 0),float(ablated_intent.get("target_ts") or 0)}
 if len(targets)!=1 or next(iter(targets))<=frozen_at_ms/1000.0:raise ValueError("twin_target_must_be_future_and_identical")
 for label,x in (("full",full_intent),("ablated",ablated_intent)):
  if bool(x.get("live_eligible")) or bool(x.get("execution_wired")):raise ValueError(label+"_execution_authority_forbidden")
  if str(x.get("transmission_status") or "NEVER_TRANSMITTED")!="NEVER_TRANSMITTED":raise ValueError(label+"_already_transmitted")
 body={"organ_id":organ_id,"opportunity_id":opportunity_id,"world":frame.world_state_hash,
  "full_cycle":full_cycle.cycle_id,"ablated_cycle":ablated_cycle.cycle_id,
  "full_cognition":full_cognition_hash,"ablated_cognition":ablated_cognition_hash,
  "full_intent":dict(full_intent),"ablated_intent":dict(ablated_intent),
  "research_campaign_id":research_campaign_id,"research_target_id":research_target_id}
 return FrozenG0Twin(_hash(body),organ_id,opportunity_id,frame.world_state_id,frame.world_state_hash,
  int(frozen_at_ms),next(iter(targets)),full_cycle.cycle_id,ablated_cycle.cycle_id,
  full_cognition_hash,ablated_cognition_hash,dict(full_intent),dict(ablated_intent),
  research_campaign_id,research_target_id)
