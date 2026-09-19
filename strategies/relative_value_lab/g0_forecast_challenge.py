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

_CONTINUATION=frozenset({"breakout_continuation","baseline_simple_momentum"})
_REVERSION=frozenset({"exhaustion_mean_reversion","baseline_simple_mean_reversion"})
_UNGROUNDED_PROBE=frozenset({"baseline_random"})

def challenge_forecast(forecast:Forecast,features:Any,*,organ_scope:str="edge_ecology")->Forecast:
 c=_ctx(features)
 if not c or forecast.abstain:return forecast
 families=set(c.get("families") or ())
 reasons=[]
 # Only evidence-semantic challenge gates. No directional bonus is created.
 payloads=c.get("family_payloads") if isinstance(c.get("family_payloads"),dict) else {}
 def first(family):
  xs=payloads.get(family) or ()
  return xs[0] if xs and isinstance(xs[0],dict) else {}
 hypothesis=str(forecast.hypothesis or "")
 continuation=hypothesis in _CONTINUATION
 reversion=hypothesis in _REVERSION
 probe=hypothesis in _UNGROUNDED_PROBE
 if organ_scope=="edge_ecology":
  # Veto-only semantics: absence of Edge evidence is not itself a veto.
  # Only evidence actually present in the FULL_HIVE path may contradict the proposal.
  if "LIQUIDITY" in families:
   liq=first("LIQUIDITY")
   imbalance=liq.get("imbalance")
   if not isinstance(imbalance,(int,float)):
    imbalance=features.book_imbalance
   if isinstance(imbalance,(int,float)) and forecast.direction in {"UP","DOWN"}:
    signed=float(imbalance) if forecast.direction=="UP" else -float(imbalance)
    if signed < -0.10:
     reasons.append("g0_liquidity_direction_conflict")
  if "FLOW" in families:
   flow=first("FLOW")
   flow_imbalance=flow.get("imbalance")
   if not isinstance(flow_imbalance,(int,float)):
    flow_imbalance=features.order_flow_imbalance
   if isinstance(flow_imbalance,(int,float)) and forecast.direction in {"UP","DOWN"}:
    signed=float(flow_imbalance) if forecast.direction=="UP" else -float(flow_imbalance)
    if signed < -0.10:
     reasons.append("g0_flow_direction_conflict")
 elif organ_scope=="horizon_context" and (continuation or probe):
  # Missing horizon evidence is neutral in an ablation. Present contradictory
  # horizon evidence may veto.
  if "HORIZON" in families:
   h=first("HORIZON");alignment=str(h.get("alignment") or "")
   wanted="ALIGNED_UP" if forecast.direction=="UP" else "ALIGNED_DOWN"
   if alignment and alignment not in {wanted,"NEUTRAL"}:reasons.append("g0_horizon_conflict")
 elif organ_scope=="temporal_participation_bee" and (continuation or probe):
  # Again, missing organ evidence is neutral; only an observed weak state vetoes.
  if "TEMPORAL_PARTICIPATION" in families:
   t=first("TEMPORAL_PARTICIPATION");state=str(t.get("activity_state") or "")
   if state and state not in {"PARTICIPATION_NORMAL","PARTICIPATION_ELEVATED"}:
    reasons.append("g0_temporal_participation_weak")
 elif organ_scope=="learning_memory":
  if "LEARNING" in families:
   for lp in payloads.get("LEARNING") or ():
    if not isinstance(lp,dict):continue
    comps=lp.get("comparisons") if isinstance(lp.get("comparisons"),dict) else {}
    d=comps.get("candidate_minus_no_trade_bps")
    if isinstance(d,(int,float)) and float(d)<=0:
     reasons.append("g0_learning_prior_no_trade_superior")
     break
 elif organ_scope=="comparison_engine" and (continuation or probe):
  if "COMPARISON" in families:
   cmp=first("COMPARISON")
   if int(cmp.get("matched_n") or 0)>=5:
    metrics=cmp.get("metrics") if isinstance(cmp.get("metrics"),dict) else {}
    vol=metrics.get("volume_zscore") if isinstance(metrics.get("volume_zscore"),dict) else {}
    delta=vol.get("delta")
    if isinstance(delta,(int,float)) and float(delta)<0:
     reasons.append("g0_comparison_participation_below_same_hour_baseline")
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
