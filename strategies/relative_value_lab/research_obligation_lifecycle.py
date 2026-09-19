"""Durable lifecycle for Queen research obligations. Research custody only."""
from __future__ import annotations
from dataclasses import dataclass,replace
from hashlib import sha256
import json
from typing import Any,Mapping
from .learning_attention import ResearchAttentionObligation
from .learning_attention_router import OrganResearchRequest

STATES=("OPEN","DISPATCHED","EVIDENCE_ATTACHED","ANSWERED","FALSIFIED")

def _id(x:Mapping[str,Any])->str:
 return sha256(json.dumps(x,sort_keys=True,separators=(",",":")).encode()).hexdigest()

@dataclass(frozen=True)
class ResearchObligationRecord:
 obligation_id:str; state:str; action:str; target:str; reason:str
 source_learning_ids:tuple[str,...]; organ_id:str|None=None; family:str|None=None
 evidence_roots:tuple[str,...]=(); answer:str|None=None
 execution_eligible:bool=False; promotion_eligible:bool=False
 def __post_init__(self):
  if self.state not in STATES: raise ValueError("invalid_obligation_state")
  if self.execution_eligible or self.promotion_eligible: raise ValueError("research_obligation_cannot_gain_authority")

class ResearchObligationLifecycle:
 def open(self,o:ResearchAttentionObligation)->ResearchObligationRecord:
  payload={"action":o.action,"target":o.target,"reason":o.reason,"source_learning_ids":o.source_learning_ids}
  return ResearchObligationRecord(_id(payload),"OPEN",o.action,o.target,o.reason,o.source_learning_ids)
 def dispatch(self,r:ResearchObligationRecord,q:OrganResearchRequest)->ResearchObligationRecord:
  if r.state!="OPEN": raise ValueError("dispatch_requires_open")
  if q.source_learning_ids!=r.source_learning_ids: raise ValueError("learning_lineage_mismatch")
  return replace(r,state="DISPATCHED",organ_id=q.organ_id,family=q.family)
 def attach_evidence(self,r:ResearchObligationRecord,*roots:str)->ResearchObligationRecord:
  if r.state!="DISPATCHED": raise ValueError("evidence_requires_dispatched")
  if not roots or any(not str(x).startswith("sha256:") for x in roots): raise ValueError("immutable_evidence_root_required")
  return replace(r,state="EVIDENCE_ATTACHED",evidence_roots=tuple(dict.fromkeys(map(str,roots))))
 def resolve(self,r:ResearchObligationRecord,*,answer:str,falsified:bool)->ResearchObligationRecord:
  if r.state!="EVIDENCE_ATTACHED": raise ValueError("resolution_requires_evidence")
  if not answer.strip(): raise ValueError("answer_required")
  return replace(r,state="FALSIFIED" if falsified else "ANSWERED",answer=answer)
