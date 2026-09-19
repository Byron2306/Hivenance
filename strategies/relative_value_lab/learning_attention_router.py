"""Route Queen learning-attention obligations to existing research organs.

This is orchestration only. It does not fetch market data, fabricate evidence,
or grant execution/promotion authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .learning_attention import ResearchAttentionObligation
from .edge_ecology import EdgeEcology

@dataclass(frozen=True)
class OrganResearchRequest:
 organ_id:str
 family:str
 action:str
 target:str
 reason:str
 required_inputs:tuple[str,...]
 source_learning_ids:tuple[str,...]
 execution_eligible:bool=False
 promotion_eligible:bool=False
 def to_dict(self)->dict[str,Any]:
  return self.__dict__.copy()

class LearningAttentionRouter:
 """Maps learned obligations onto organs that already own the responsibility."""
 routes={
  "time_shift_placebo":("temporal_observer","TEMPORAL",("public_future_observations","candidate_horizon","world_graph")),
  "same_root":("lineage_guard","LINEAGE",("world_graph","evidence_roots","lineage_registry")),
  "independent lineage":("lineage_guard","LINEAGE",("world_graph","evidence_roots","lineage_registry")),
  "cost":("edge_ecology","LIQUIDITY",("bid_depth","ask_depth","spread_bps","previous_depth")),
  "stale":("public_observer","REFRESH",("source_identity","last_observed_at","freshness_policy")),
  "flow":("edge_ecology","FLOW",("taker_buy_volume","taker_sell_volume","previous_imbalance")),
  "liquidity":("edge_ecology","LIQUIDITY",("bid_depth","ask_depth","spread_bps","previous_depth")),
  "state":("counterpoint","COUNTERPOINT",("world_graph","learning_brief","matched_controls")),
 }
 def route(self,o:ResearchAttentionObligation)->OrganResearchRequest:
  low=o.target.lower()
  key=next((k for k in self.routes if k.replace("_"," ") in low),None)
  if key is None: return OrganResearchRequest("hypothesis_swarm","HYPOTHESIS",o.action,o.target,o.reason,("world_graph","learning_brief"),o.source_learning_ids)
  organ,family,inputs=self.routes[key]
  return OrganResearchRequest(organ,family,o.action,o.target,o.reason,inputs,o.source_learning_ids)

 def invoke_edge(self,request:OrganResearchRequest,**observed:float):
  """Invoke only when caller supplies the actual observed evidence."""
  if request.organ_id!="edge_ecology": raise ValueError("request_not_edge_ecology")
  if request.family=="FLOW":
   return EdgeEcology.flow_voice(taker_buy_volume=observed["taker_buy_volume"],taker_sell_volume=observed["taker_sell_volume"],previous_imbalance=observed.get("previous_imbalance"))
  if request.family=="LIQUIDITY":
   return EdgeEcology.liquidity_voice(bid_depth=observed["bid_depth"],ask_depth=observed["ask_depth"],spread_bps=observed["spread_bps"],previous_bid_depth=observed.get("previous_bid_depth"),previous_ask_depth=observed.get("previous_ask_depth"))
  raise ValueError("unsupported_edge_family")
