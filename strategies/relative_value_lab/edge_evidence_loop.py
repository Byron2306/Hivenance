"""Close the learning-attention -> Edge evidence -> WorldGraph seam."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping,Any
from .edge_ecology import EdgeEcology
from .learning_attention_router import LearningAttentionRouter,OrganResearchRequest
from .world_graph import WorldGraph,WorldGraphNode
from .world_graph_adapters import add_edge_ecology

@dataclass(frozen=True)
class EdgeEvidenceObservation:
 source_id:str
 evidence_root:str
 observed:Mapping[str,float]
 def __post_init__(self):
  if not self.evidence_root.startswith("sha256:"): raise ValueError("edge_evidence_root_unbound")

def observe_into_graph(graph:WorldGraph,request:OrganResearchRequest,evidence:EdgeEvidenceObservation,*,timestamp_ms:int,pair_id:str)->WorldGraphNode:
 """Invoke the existing Edge voice only from supplied evidence, then graph it."""
 router=LearningAttentionRouter()
 voice=router.invoke_edge(request,**dict(evidence.observed))
 snap=EdgeEcology().snapshot(timestamp_ms=timestamp_ms,pair_id=pair_id,voices=(voice,))
 return add_edge_ecology(graph,snapshot=snap,created_at_ms=timestamp_ms,family_source_roots={voice.family:(evidence.evidence_root,)})[0]
