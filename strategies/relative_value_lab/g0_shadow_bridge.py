"""Bind canonical Phoenix adversarial Shadow receipts into G0 evidence intake.

This bridge does not pretend candidate-vs-control is organ-ablation evidence.
It exposes settled prospective Shadow learning and its exact custody so G0 can
consume it as cognition input while organ economic usefulness waits for paired
FULL_HIVE-vs-organ-blind settlements.
"""
from __future__ import annotations
import json
from dataclasses import dataclass,asdict
from typing import Any,Mapping,Sequence

@dataclass(frozen=True)
class G0ShadowEvidence:
 receipt_id:str; bundle_id:str; settled_ts:float; learning:Mapping[str,Any]
 candidate_net_return_bps:float|None; controls:tuple[Mapping[str,Any],...]
 authority:str="PROSPECTIVE_SHADOW_RESEARCH_ONLY"
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self):return asdict(self)

def load_canonical_shadow_evidence(data_store:Any,*,limit:int=250)->tuple[G0ShadowEvidence,...]:
 rows=data_store.get_phase5_adversarial_shadow_receipts(limit=limit)
 out=[]
 for row in rows:
  p=row.get("payload")
  if isinstance(p,str):p=json.loads(p)
  if not isinstance(p,Mapping):continue
  if p.get("authority")!="PROSPECTIVE_SHADOW_RESEARCH_ONLY":raise ValueError("invalid_shadow_authority")
  if p.get("execution_eligible") is not False or p.get("promotion_eligible") is not False:
   raise ValueError("shadow_authority_escalation")
  learning=p.get("learning") or {};settlement=p.get("settlement") or {}
  candidate=settlement.get("candidate") or {}
  out.append(G0ShadowEvidence(str(p.get("receipt_id") or row.get("receipt_id") or ""),
   str(p.get("bundle_id") or ""),float(p.get("settled_ts") or 0.0),dict(learning),
   candidate.get("net_return_bps"),tuple(settlement.get("controls") or ())))
 return tuple(out)

def shadow_learning_receipts(data_store:Any,*,limit:int=250)->tuple[Mapping[str,Any],...]:
 return tuple(x.learning for x in load_canonical_shadow_evidence(data_store,limit=limit))
