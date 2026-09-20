"""Research-only adapter from Synthesis cognition into Phoenix hypothesis features.

It does not choose direction, probability, expected move, or net return. It only
binds inspectable synthesis context into FeatureVector.values so existing
HypothesisCompetition models may react to it. FULL_HIVE and organ-blind paths
are evaluated independently by the unchanged Phoenix competition.
"""
from __future__ import annotations
from dataclasses import replace
from typing import Any
from strategies.volatility_breakout.models import FeatureVector
from .hypothesis_statistics_bridge import bind_statistical_context
from .research_context import build_research_context, bind_research_context_values
from .research_context_router import project_research_context

def bind_synthesis_context(feature:FeatureVector,cycle:Any)->FeatureVector:
 if str(getattr(cycle,"world_state_id",""))!=str(feature.values.get("world_state_id") or getattr(cycle,"world_state_id","")):
  raise ValueError("feature_world_state_mismatch")
 values=dict(feature.values or {})
 family_payloads={}
 for node in getattr(cycle.queen_view,"nodes",()):
  raw=dict(node.payload)

  # Canonical Phase-5 evidence enters Queen through BeeEvidence.
  # Forecast challenges operate on the evidence-family payload itself,
  # not on the custody envelope, so expose the inner payload while
  # preserving Bee metadata for audit.
  if (
   raw.get("schema")=="hivenance_bee_evidence_v1"
   and isinstance(raw.get("payload"),dict)
  ):
   exposed=dict(raw["payload"])
   exposed["_bee_evidence"]={
    "evidence_id":raw.get("evidence_id"),
    "family":raw.get("family"),
    "source_kind":raw.get("source_kind"),
    "source_ids":tuple(raw.get("source_ids") or ()),
    "evidence_roots":tuple(raw.get("evidence_roots") or ()),
    "lineage":tuple(raw.get("lineage") or ()),
    "transformation_version":raw.get("transformation_version"),
    "observed_at_ms":raw.get("observed_at_ms"),
    "available_at_ms":raw.get("available_at_ms"),
    "missingness":tuple(raw.get("missingness") or ()),
    "abstention":bool(raw.get("abstention")),
   }
   family_payloads.setdefault(
    str(node.family),[]
   ).append(exposed)
  else:
   family_payloads.setdefault(
    str(node.family),[]
   ).append(raw)
 values["synthesis_context"]={
  "cycle_id":cycle.cycle_id,
  "world_state_id":cycle.world_state_id,
  "world_state_hash":cycle.world_state_hash,
  "families":tuple(cycle.queen_view.families),
  "family_payloads":{k:tuple(v) for k,v in family_payloads.items()},
  "learning":dict(cycle.learning),
  "attention_obligations":tuple(cycle.attention_obligations),
  "organ_requests":tuple(cycle.organ_requests),
  "authority":"RESEARCH_CONTEXT_ONLY",
  "execution_eligible":False,
 }
 statistical=cycle.learning.get("probabilistic_synthesis") if isinstance(cycle.learning,dict) else None
 regime_state=None
 statistical_family=family_payloads.get("STATISTICAL_SYNTHESIS") or ()
 if statistical_family and isinstance(statistical_family[0],dict):
  statistical = statistical or statistical_family[0]
 regime_family=family_payloads.get("REGIME_CONTEXT") or family_payloads.get("REGIME") or ()
 if regime_family and isinstance(regime_family[0],dict):
  regime_state=regime_family[0]
 research_context=build_research_context(
  world_state_id=cycle.world_state_id,
  world_state_hash=cycle.world_state_hash,
  as_of_ms=int(feature.timestamp_ms),
  feature_values=values,
  synthesis_context=values["synthesis_context"],
  statistical_state=statistical,
  regime_state=regime_state,
 )
 values=bind_research_context_values(values,research_context)
 values["organ_context_views"]={
  organ_id:project_research_context(research_context,organ_id=organ_id).to_dict()
  for organ_id in (
   "hypothesis_competition",
   "strategy_workers",
   "ml_challenger",
   "market_hunting",
   "mystique",
   "pollen_economy",
   "cognitive_metabolism",
   "recursive_queen",
   "conducting_queen",
  )
 }
 bound=replace(feature,values=values)
 if statistical is not None:
  bound=bind_statistical_context(bound,statistical)
 return bound

def evaluate_synthesis_pair(*,competition:Any,feature:FeatureVector,horizons:tuple[int,...],
 full_cycle:Any,ablated_cycle:Any)->dict[str,Any]:
 if full_cycle.world_state_hash!=ablated_cycle.world_state_hash:
  raise ValueError("paired_hypothesis_evaluation_requires_identical_world")
 full_feature=bind_synthesis_context(feature,full_cycle)
 blind_feature=bind_synthesis_context(feature,ablated_cycle)
 full=tuple(competition.evaluate(full_feature,horizons))
 blind=tuple(competition.evaluate(blind_feature,horizons))
 return {"full_forecasts":full,"ablated_forecasts":blind,
  "full_cycle_id":full_cycle.cycle_id,"ablated_cycle_id":ablated_cycle.cycle_id,
  "world_state_hash":full_cycle.world_state_hash,"execution_eligible":False,"promotion_eligible":False}
