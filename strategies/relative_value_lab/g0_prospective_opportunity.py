"""Freeze one genuine G0 prospective opportunity before the outcome exists.

The caller must supply intents independently compiled from FULL_HIVE and the
organ-blind cycle. This module binds them to the measured cognition hashes and
persists the sealed twin. It never invents a forecast or mutates direction.
"""
from __future__ import annotations
from typing import Any,Mapping
from .synthesis_influence import measure_influence
from .g0_twin_freeze import freeze_shadow_twin
from .g0_twin_store import persist_frozen_twin

def freeze_prospective_opportunity(*,data_store:Any,organ_id:str,opportunity_id:str,
 frame:Any,full_cycle:Any,ablated_cycle:Any,full_intent:Mapping[str,Any],
 ablated_intent:Mapping[str,Any],frozen_at_ms:int)->dict[str,Any]:
 inf=measure_influence(organ_id=organ_id,full=full_cycle,ablated=ablated_cycle)
 if not inf.cognition_changed:raise ValueError("organ_did_not_change_cognition")
 twin=freeze_shadow_twin(organ_id=organ_id,opportunity_id=opportunity_id,frame=frame,
  full_cycle=full_cycle,ablated_cycle=ablated_cycle,
  full_cognition_hash=inf.full_cognition_hash,ablated_cognition_hash=inf.ablated_cognition_hash,
  full_intent=full_intent,ablated_intent=ablated_intent,frozen_at_ms=frozen_at_ms)
 created=persist_frozen_twin(data_store,twin)
 return {"created":bool(created),"twin_freeze_id":twin.twin_freeze_id,
  "organ_id":organ_id,"opportunity_id":opportunity_id,"world_state_hash":frame.world_state_hash,
  "cognition_changed":True,"full_cognition_hash":inf.full_cognition_hash,
  "ablated_cognition_hash":inf.ablated_cognition_hash,
  "authority":twin.authority,"execution_eligible":False,"promotion_eligible":False}
