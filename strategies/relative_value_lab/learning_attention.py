"""Convert qualified learning into bounded research-attention obligations.

This is the seam from memory to cognition. It may request observation,
challenge or comparison. It cannot request a trade or promote a hypothesis.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .learning_retrieval import LearningBrief

ALLOWED_ACTIONS=frozenset({"OBSERVE","CHALLENGE","COMPARE","CORROBORATE","REFRESH","WAIT"})

@dataclass(frozen=True)
class ResearchAttentionObligation:
 action:str
 target:str
 reason:str
 source_learning_ids:tuple[str,...]
 execution_eligible:bool=False
 promotion_eligible:bool=False
 def __post_init__(self):
  if self.action not in ALLOWED_ACTIONS: raise ValueError("unsupported_learning_attention_action")
 def to_dict(self)->dict[str,Any]:
  return {"action":self.action,"target":self.target,"reason":self.reason,"source_learning_ids":self.source_learning_ids,
   "execution_eligible":False,"promotion_eligible":False}

def obligations_from_learning(brief:LearningBrief)->tuple[ResearchAttentionObligation,...]:
 out=[]
 for target in brief.next_falsifications:
  low=target.lower()
  action="OBSERVE" if any(k in low for k in ("root","flow","liquidity","evidence")) else "CHALLENGE"
  out.append(ResearchAttentionObligation(action,target,"unresolved learning falsification",brief.learning_ids))
 for claim in brief.supported_claims:
  out.append(ResearchAttentionObligation("CHALLENGE",claim,"supported historical claim requires adversarial counterpoint",brief.learning_ids))
 return tuple(out)
