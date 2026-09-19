"""Comparative learning receipt from one settled adversarial shadow court."""
from __future__ import annotations
from typing import Any
from .adversarial_shadow_settlement import AdversarialBundleSettlement

def adversarial_learning_receipt(s:AdversarialBundleSettlement)->dict[str,Any]:
 cand=s.candidate.net_return_bps if s.candidate is not None else None
 controls={x.control_type:x for x in s.controls}
 comparisons={}
 if cand is not None:
  for k,x in controls.items():
   if x.status not in {"UNSETTLED","PENDING"}: comparisons["candidate_minus_"+k.lower()+"_bps"]=cand-x.net_return_bps
 return {"schema":"hivenance_adversarial_shadow_learning_v1","learning_id":"shadow:"+s.bundle_id,
  "status":"PROSPECTIVE_SHADOW_EVIDENCE","authority":"PROSPECTIVE_SHADOW_RESEARCH_ONLY",
  "candidate_net_return_bps":cand,"comparisons":comparisons,
  "unsettled_controls":[k for k,x in controls.items() if x.status in {"UNSETTLED","PENDING"}],
  "execution_eligible":False,"promotion_eligible":False,
  "interpretation":"Comparative shadow evidence only; not live execution authority."}
