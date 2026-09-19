"""Thin research-only runtime joining the canonical WorldGraph cognition spine.

This module deliberately does not grant order, execution, or promotion authority.
It makes invocation/influence inspectable so G0 can ablate organs against an
identical observation tape.
"""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass
from typing import Any,Mapping,Sequence
from .world_graph import WorldGraph,QueenView
from .world_score import CanonicalScoreFrame
from .world_graph_adapters import add_horizon_context,add_edge_ecology,add_temporal_participation
from .learning_memory import add_learning_receipt
from .learning_retrieval import learning_brief
from .learning_attention import obligations_from_learning
from .learning_attention_router import LearningAttentionRouter
from .comparison_engine import add_comparison_result

def _digest(v:Any)->str:
 raw=json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()
 return "sha256:"+hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class OrganReceipt:
 organ_id:str; state:str; input_roots:tuple[str,...]; output_node_ids:tuple[str,...]
 changed_graph:bool; details:Mapping[str,Any]
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self): return asdict(self)

@dataclass(frozen=True)
class SynthesisCycle:
 cycle_id:str; world_state_id:str; world_state_hash:str; queen_view:QueenView
 organ_receipts:tuple[OrganReceipt,...]; learning:Mapping[str,Any]
 attention_obligations:tuple[Mapping[str,Any],...]=(); organ_requests:tuple[Mapping[str,Any],...]=()
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self): return {"cycle_id":self.cycle_id,"world_state_id":self.world_state_id,
  "world_state_hash":self.world_state_hash,"queen_view":self.queen_view.to_dict(),
  "organ_receipts":tuple(x.to_dict() for x in self.organ_receipts),"learning":dict(self.learning),
  "attention_obligations":self.attention_obligations,"organ_requests":self.organ_requests,
  "execution_eligible":False,"promotion_eligible":False}

class SynthesisRuntime:
 """Compose already-existing organs over one immutable observed frame."""

 def run(self,*,frame:CanonicalScoreFrame,now_ms:int,horizon:Any|None=None,
         horizon_roots:Sequence[str]=(),edge_snapshot:Any|None=None,
         edge_roots:Mapping[str,Sequence[str]]|None=None,
         temporal_participation:Any|None=None,
         learning_receipts:Sequence[Mapping[str,Any]]=(),comparison_results:Sequence[Any]=(),
         disabled_organs:Sequence[str]=())->SynthesisCycle:
  disabled={str(x) for x in disabled_organs};g=WorldGraph(frame);rs=[]

  def receipt(organ,state,roots=(),nodes=(),**details):
   rs.append(OrganReceipt(organ,state,tuple(sorted(set(roots))),
     tuple(n.node_id for n in nodes),bool(nodes),details))

  if horizon is None or "horizon_context" in disabled:
   receipt("horizon_context","DISABLED" if "horizon_context" in disabled else "AVAILABLE_NOT_INVOKED")
  else:
   n=add_horizon_context(g,context=horizon,created_at_ms=now_ms,source_roots=horizon_roots)
   receipt("horizon_context","INVOKED",horizon_roots,(n,))

  if edge_snapshot is None or "edge_ecology" in disabled:
   receipt("edge_ecology","DISABLED" if "edge_ecology" in disabled else "AVAILABLE_NOT_INVOKED")
  else:
   roots=edge_roots or {}
   ns=add_edge_ecology(g,snapshot=edge_snapshot,created_at_ms=now_ms,family_source_roots=roots)
   receipt("edge_ecology","INVOKED",(r for xs in roots.values() for r in xs),ns)

  if temporal_participation is None or "temporal_participation_bee" in disabled:
   receipt("temporal_participation_bee","DISABLED" if "temporal_participation_bee" in disabled else "AVAILABLE_NOT_INVOKED")
  else:
   n=add_temporal_participation(g,evidence=temporal_participation,created_at_ms=now_ms)
   receipt("temporal_participation_bee","INVOKED",(temporal_participation.evidence_root,),(n,))

  learned=[]
  if "learning_memory" in disabled:
   receipt("learning_memory","DISABLED")
  else:
   for x in learning_receipts: learned.append(add_learning_receipt(g,x,created_at_ms=now_ms))
   receipt("learning_memory","INVOKED" if learned else "AVAILABLE_NOT_INVOKED",
           (r for n in learned for r in n.evidence_roots),learned,count=len(learned))

  compared=[]
  if "comparison_engine" in disabled:
   receipt("comparison_engine","DISABLED")
  else:
   for result in comparison_results: compared.append(add_comparison_result(g,result=result,created_at_ms=now_ms))
   receipt("comparison_engine","INVOKED" if compared else "AVAILABLE_NOT_INVOKED",
           (r for n in compared for r in n.evidence_roots),compared,count=len(compared))

  view=g.queen_view(created_at_ms=now_ms,expected_families=("HORIZON","FLOW","LIQUIDITY","TEMPORAL_PARTICIPATION","LEARNING","COMPARISON"))
  brief=learning_brief(view)
  obligations=obligations_from_learning(brief)
  router=LearningAttentionRouter()
  requests=tuple(router.route(o) for o in obligations)
  body={"world_state_id":frame.world_state_id,"world_state_hash":frame.world_state_hash,
        "organs":[x.to_dict() for x in rs],"nodes":[n.node_id for n in view.nodes]}
  return SynthesisCycle("syn_"+_digest(body).split(":",1)[1][:24],frame.world_state_id,
    frame.world_state_hash,view,tuple(rs),brief.to_dict(),
    tuple(o.to_dict() for o in obligations),tuple(r.to_dict() for r in requests),False,False)
