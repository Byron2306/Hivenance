"""Evidence-semantic G0 challenge layer for Phoenix forecasts.

This layer may only challenge/abstain an existing forecast when synthesis
evidence contradicts the same market evidence family. It cannot originate or
flip direction and cannot improve expected economics.
"""
from __future__ import annotations
from dataclasses import replace
from typing import Any
from strategies.volatility_breakout.models import Forecast

def _ctx(features:Any)->dict:
 v=features.values if isinstance(features.values,dict) else {}
 x=v.get("synthesis_context")
 return x if isinstance(x,dict) else {}

def challenge_forecast(forecast:Forecast,features:Any)->Forecast:
 c=_ctx(features)
 if not c or forecast.abstain:return forecast
 families=set(c.get("families") or ())
 reasons=[]
 # Only evidence-semantic challenge gates. No directional bonus is created.
 if forecast.hypothesis=="breakout_continuation":
  if features.order_flow_imbalance is not None and "FLOW" not in families:
   reasons.append("g0_flow_not_corroborated")
  if features.book_imbalance is not None and "LIQUIDITY" not in families:
   reasons.append("g0_liquidity_not_corroborated")
 if forecast.hypothesis=="exhaustion_mean_reversion":
  if features.book_imbalance is not None and "LIQUIDITY" not in families:
   reasons.append("g0_liquidity_not_corroborated")
 if not reasons:return forecast
 inputs=dict(forecast.inputs or {});inputs["g0_synthesis_challenge"]={
  "cycle_id":c.get("cycle_id"),"world_state_hash":c.get("world_state_hash"),
  "families":tuple(sorted(families)),"reasons":tuple(reasons),
  "authority":"RESEARCH_VETO_ONLY"}
 return replace(forecast,direction="ABSTAIN",probability_positive_net=None,
  expected_move_bps=None,expected_net_bps=None,abstain=True,
  reason=reasons[0],reasons=tuple(forecast.reasons)+tuple(reasons),inputs=inputs,
  execution_eligible=False)

def evaluate_with_synthesis_challenge(competition:Any,features:Any,horizons:Any)->list[Forecast]:
 return [challenge_forecast(x,features) for x in competition.evaluate(features,horizons)]
