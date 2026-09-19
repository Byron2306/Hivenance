"""Queen-facing retrieval of qualified Hive learning.

This is an attention/read seam only. It never promotes historical memory into
observed truth or execution authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any,Mapping,Sequence
from .world_graph import QueenView,WorldGraphNode

@dataclass(frozen=True)
class LearningBrief:
 learning_ids: tuple[str,...]
 statuses: tuple[str,...]
 supported_claims: tuple[str,...]
 limitations: tuple[str,...]
 weakened_explanations: tuple[str,...]
 next_falsifications: tuple[str,...]
 authorities: tuple[str,...]
 execution_eligible: bool=False
 promotion_eligible: bool=False
 def to_dict(self)->dict[str,Any]:
  return {"learning_ids":self.learning_ids,"statuses":self.statuses,"supported_claims":self.supported_claims,
   "limitations":self.limitations,"weakened_explanations":self.weakened_explanations,
   "next_falsifications":self.next_falsifications,"authorities":self.authorities,
   "execution_eligible":False,"promotion_eligible":False}

def learning_brief(view:QueenView)->LearningBrief:
 nodes=[n for n in view.nodes if n.family=="LEARNING"]
 ids=[];statuses=[];claims=[];limits=[];weak=[];nxt=[];auth=[]
 for n in nodes:
  p=dict(n.payload);ids.append(str(p.get("learning_id",n.node_id)));statuses.append(str(p.get("status","UNKNOWN")));auth.append(str(p.get("authority",n.authority)))
  it=p.get("interpretation") or {}
  if isinstance(it,Mapping):
   if it.get("supported"):claims.append(str(it["supported"]))
   for k,v in it.items():
    if k!="supported" and v:limits.append(f"{k}: {v}")
  weak.extend(str(x) for x in p.get("falsified_or_weakened_explanations",()))
  nxt.extend(str(x) for x in p.get("next_falsification",()))
  if str(p.get("authority",""))=="PROSPECTIVE_SHADOW_RESEARCH_ONLY":
   comparisons=p.get("comparisons") if isinstance(p.get("comparisons"),Mapping) else {}
   for name,delta in comparisons.items():
    claims.append(f"{name}={delta} bps")
   for control in p.get("unsettled_controls",()):
    nxt.append(f"settle shadow control {control}")
 def uq(xs):return tuple(dict.fromkeys(xs))
 return LearningBrief(uq(ids),uq(statuses),uq(claims),uq(limits),uq(weak),uq(nxt),uq(auth))
