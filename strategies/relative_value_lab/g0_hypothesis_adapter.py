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

def bind_synthesis_context(feature:FeatureVector,cycle:Any)->FeatureVector:
 if str(getattr(cycle,"world_state_id",""))!=str(feature.values.get("world_state_id") or getattr(cycle,"world_state_id","")):
  raise ValueError("feature_world_state_mismatch")
 values=dict(feature.values or {})
 values["synthesis_context"]={
  "cycle_id":cycle.cycle_id,
  "world_state_id":cycle.world_state_id,
  "world_state_hash":cycle.world_state_hash,
  "families":tuple(cycle.queen_view.families),
  "learning":dict(cycle.learning),
  "attention_obligations":tuple(cycle.attention_obligations),
  "organ_requests":tuple(cycle.organ_requests),
  "authority":"RESEARCH_CONTEXT_ONLY",
  "execution_eligible":False,
 }
 return replace(feature,values=values)

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
