"""Autonomous prospective G0 generation from the live Phoenix feature pass.

Uses one observed FeatureVector to build one immutable world, runs FULL_HIVE and
Edge-blind cognition, lets the unchanged Phoenix model forecast, applies the
research-only semantic challenge, and freezes only decisions that actually
diverge before the target exists.
"""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict
from typing import Any
from strategies.volatility_breakout.shadow_flight import ShadowIntentBuilder
from strategies.volatility_breakout.shadow_models import ShadowFreeze
from .world_score import ScoreObservation,CanonicalWorldScore
from .edge_ecology import EdgeEcology
from .synthesis_runtime import SynthesisRuntime
from .g0_hypothesis_adapter import bind_synthesis_context
from .g0_forecast_challenge import challenge_forecast
from .g0_forecast_binding import freeze_forecast_pair
from .g0_live_evidence import horizon_from_feature,temporal_from_store,latest_shadow_learning,same_hour_comparison
from .g1_polyphonic_bridge import quorum_for_forecast,apply_quorum_gate
from .g1_post_cognition_freeze import freeze_post_cognition_pair
from .g1_conducting_queen_bridge import queen_receipt_for_forecast,apply_queen_gate

def _hash(x:Any)->str:
 return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def _freeze(record:dict[str,Any])->ShadowFreeze:
 return ShadowFreeze(freeze_id=str(record.get("freeze_id") or ""),phase4_run_id=str(record.get("phase4_run_id") or ""),
  candidate_key=str(record.get("candidate_key") or ""),model_id=str(record.get("model_id") or ""),
  order_policy=str(record.get("order_policy") or ""),approved_by=str(record.get("approved_by") or ""),
  approved_ts=float(record.get("approved_ts") or 0),phase4_dataset_hash=str(record.get("phase4_dataset_hash") or ""),
  config_hash=str(record.get("config_hash") or ""),symbol=str(record.get("symbol") or "") or None,
  direction=str(record.get("direction") or "").upper() or None,status=str(record.get("status") or "ACTIVE"))

def _row(f:Any,*,venue:str,world_hash:str,path:str,entry_price:float|None)->dict[str,Any]:
 d=asdict(f) if hasattr(f,"__dataclass_fields__") else dict(f)
 ts=float(d.get("timestamp_ms") or 0)/1000.0;h=int(d.get("horizon_seconds") or 0)
 d.update({"forecast_id":_hash({"world":world_hash,"model":d.get("model_id"),"horizon":h,"path":path}),
  "venue":venue,"ts":ts,"target_ts":ts+h,"entry_price":entry_price,
  "target_timestamp_ms":int((ts+h)*1000),"execution_eligible":False})
 return d

def _decision(f:Any)->tuple[Any,...]:
 return (bool(getattr(f,"abstain",False)),str(getattr(f,"direction","ABSTAIN")),
  getattr(f,"expected_net_bps",None),getattr(f,"probability_positive_net",None))

class G0LiveLoop:
 def __init__(self,cfg:Any,runtime:SynthesisRuntime|None=None)->None:
  self.cfg=cfg;self.runtime=runtime or SynthesisRuntime();self.builder=ShadowIntentBuilder(cfg)

 def process_feature(self,*,data_store:Any,competition:Any,feature:Any,venue:str,now_ms:int,
                     horizons:tuple[int,...])->dict[str,Any]:
  out={"examined":0,"eligible":0,"diverged":0,"frozen":0,"skipped":0,"errors":0,"by_organ":{}}
  def bump(organ_id:str,key:str,amount:int=1)->None:
   bucket=out["by_organ"].setdefault(str(organ_id),{"examined":0,"eligible":0,"diverged":0,"frozen":0,"skipped":0,"errors":0,"raw_non_abstain":0,"raw_abstain":0,"raw_abstain_reasons":{}})
   bucket[key]+=int(amount)
   out[key]+=int(amount)
  def raw_state(organ_id:str,forecast:Any)->None:
   bucket=out["by_organ"].setdefault(str(organ_id),{"examined":0,"eligible":0,"diverged":0,"frozen":0,"skipped":0,"errors":0,"raw_non_abstain":0,"raw_abstain":0,"raw_abstain_reasons":{}})
   if bool(getattr(forecast,"abstain",False)):
    bucket["raw_abstain"]+=1
    reasons=tuple(getattr(forecast,"reasons",()) or ())
    if not reasons:
     reason=str(getattr(forecast,"reason","") or "unspecified")
     reasons=(reason,)
    for reason in reasons:
     key=str(reason or "unspecified")
     bucket["raw_abstain_reasons"][key]=int(bucket["raw_abstain_reasons"].get(key) or 0)+1
   else:
    bucket["raw_non_abstain"]+=1
  record=data_store.get_phase5_active_freeze() if hasattr(data_store,"get_phase5_active_freeze") else {}
  research_campaign_id=None;research_target_id=None
  if record:
   freezes=(_freeze(record),)
  else:
   from .g1_research_target import (
    ensure_g1_research_target,get_latest_g1_research_target,shadow_freezes_from_research_target,
   )
   target=get_latest_g1_research_target(data_store)
   if target is None:
    target=ensure_g1_research_target(data_store,self.cfg,created_ts=float(now_ms)/1000.0)
   freezes=shadow_freezes_from_research_target(target)
   research_campaign_id=str(target.get("campaign_id") or "") or None
   research_target_id=str(target.get("target_id") or "") or None
  freeze_by_model={str(x.model_id):x for x in freezes if x.status=="ACTIVE"}
  if not freeze_by_model:return out
  if feature.book_imbalance is None or feature.depth_usd_25bps is None or feature.spread_bps is None:return out
  payload=asdict(feature);root=_hash(payload)
  observed=min(int(feature.timestamp_ms),int(now_ms))
  obs=ScoreObservation(_hash({"root":root,"symbol":feature.symbol})[-24:],str(venue),"public_market_feature",
   str(feature.symbol),observed,int(now_ms),root,payload)
  frame=CanonicalWorldScore.assemble(observations=(obs,),assembled_at_ms=int(now_ms),
   freshness_window_ms=max(1000,int(getattr(self.cfg,"phase1_observation_stale_after_sec",180) or 180)*1000))
  total=max(0.0,float(feature.depth_usd_25bps));imb=max(-1.0,min(1.0,float(feature.book_imbalance)))
  bid=total*(1.0+imb)/2.0;ask=total*(1.0-imb)/2.0
  snap=EdgeEcology().snapshot(timestamp_ms=int(feature.timestamp_ms),pair_id=str(feature.symbol),voices=(
   EdgeEcology.liquidity_voice(bid_depth=bid,ask_depth=ask,spread_bps=float(feature.spread_bps)),))
  horizon=horizon_from_feature(feature)
  temporal=temporal_from_store(data_store,feature)
  learning=latest_shadow_learning(data_store)
  comparison=same_hour_comparison(data_store,feature)
  full=self.runtime.run(frame=frame,now_ms=int(now_ms),horizon=horizon,horizon_roots=(root,) if horizon else (),
   edge_snapshot=snap,edge_roots={"LIQUIDITY":(root,)},temporal_participation=temporal,
   learning_receipts=learning,comparison_results=(comparison,) if comparison is not None else ())
  entry={"price":feature.price,"data_quality":feature.data_quality,"spread_bps":feature.spread_bps,
   "depth_usd_25bps":feature.depth_usd_25bps}
  experiments=[("edge_ecology","EDGE_BLIND")]
  if horizon is not None:experiments.append(("horizon_context","HORIZON_BLIND"))
  if temporal is not None:experiments.append(("temporal_participation_bee","TEMPORAL_BLIND"))
  if learning:experiments.append(("learning_memory","LEARNING_BLIND"))
  if comparison is not None:experiments.append(("comparison_engine","COMPARISON_BLIND"))
  full_feature=bind_synthesis_context(feature,full)
  for organ_id,path_label in experiments:
   blind=self.runtime.run(frame=frame,now_ms=int(now_ms),horizon=horizon,horizon_roots=(root,) if horizon else (),
    edge_snapshot=snap,edge_roots={"LIQUIDITY":(root,)},temporal_participation=temporal,
    learning_receipts=learning,comparison_results=(comparison,) if comparison is not None else (),
    disabled_organs=(organ_id,))
   blind_feature=bind_synthesis_context(feature,blind)
   full_forecasts=competition.evaluate(full_feature,horizons)
   blind_forecasts=competition.evaluate(blind_feature,horizons)
   blind_by={(x.model_id,int(x.horizon_seconds)):x for x in blind_forecasts}
   for raw_full in full_forecasts:
    freeze=freeze_by_model.get(str(raw_full.model_id))
    if freeze is None:continue
    if freeze.symbol and str(feature.symbol)!=freeze.symbol:continue
    raw_blind=blind_by.get((raw_full.model_id,int(raw_full.horizon_seconds)))
    if raw_blind is None:continue
    bump(organ_id,"examined")
    raw_state(organ_id,raw_full)
    full_fc=challenge_forecast(raw_full,full_feature,organ_scope=organ_id)
    blind_fc=challenge_forecast(raw_blind,blind_feature,organ_scope=organ_id)
    if freeze.direction and not full_fc.abstain and str(full_fc.direction).upper()!=str(freeze.direction).upper():
     bump(organ_id,"skipped");continue
    bump(organ_id,"eligible")
    if _decision(full_fc)==_decision(blind_fc):
     bump(organ_id,"skipped");continue
    bump(organ_id,"diverged")
    try:
     ff=_row(full_fc,venue=venue,world_hash=frame.world_state_hash,path="FULL_HIVE",entry_price=feature.price)
     bf=_row(blind_fc,venue=venue,world_hash=frame.world_state_hash,path=path_label,entry_price=feature.price)
     opportunity=_hash({"world":frame.world_state_hash,"organ":organ_id,"model":freeze.model_id,
      "horizon":int(full_fc.horizon_seconds)})
     r=freeze_forecast_pair(data_store=data_store,builder=self.builder,freeze=freeze,organ_id=organ_id,
      opportunity_id=opportunity,frame=frame,full_cycle=full,ablated_cycle=blind,
      full_forecast=ff,ablated_forecast=bf,full_observation=entry,ablated_observation=entry,frozen_at_ms=int(now_ms),
      research_campaign_id=research_campaign_id,research_target_id=research_target_id)
     if r.get("created"):bump(organ_id,"frozen")
     else:bump(organ_id,"skipped")
    except Exception:
     bump(organ_id,"errors")

  # Post-cognition organs are evaluated independently against the exact raw
  # Phoenix forecast, never against one another's modified output.
  for raw_full in competition.evaluate(full_feature,horizons):
   freeze=freeze_by_model.get(str(raw_full.model_id))
   if freeze is None or raw_full.abstain:continue
   if freeze.symbol and str(feature.symbol)!=freeze.symbol:continue
   if freeze.direction and str(raw_full.direction).upper()!=str(freeze.direction).upper():continue

   bump("polyphonic_quorum","examined");bump("polyphonic_quorum","eligible");raw_state("polyphonic_quorum",raw_full)
   try:
    receipt=quorum_for_forecast(cycle=full,forecast=raw_full,feature=full_feature)
    gated=apply_quorum_gate(raw_full,receipt)
    if _decision(gated)!=_decision(raw_full):
     bump("polyphonic_quorum","diverged")
     ff=_row(gated,venue=venue,world_hash=frame.world_state_hash,path="QUORUM_GATED",entry_price=feature.price)
     bf=_row(raw_full,venue=venue,world_hash=frame.world_state_hash,path="QUORUM_BLIND",entry_price=feature.price)
     opportunity=_hash({"world":frame.world_state_hash,"organ":"polyphonic_quorum","model":freeze.model_id,
      "horizon":int(raw_full.horizon_seconds)})
     r=freeze_post_cognition_pair(data_store=data_store,builder=self.builder,freeze=freeze,
      organ_id="polyphonic_quorum",opportunity_id=opportunity,frame=frame,
      full_forecast=ff,ablated_forecast=bf,full_observation=entry,ablated_observation=entry,
      intervention_receipt=receipt.to_dict(),frozen_at_ms=int(now_ms),
      research_campaign_id=research_campaign_id,research_target_id=research_target_id)
     if r.get("created"):bump("polyphonic_quorum","frozen")
     else:bump("polyphonic_quorum","skipped")
    else:bump("polyphonic_quorum","skipped")
   except Exception:
    bump("polyphonic_quorum","errors")

   bump("conducting_queen","examined");bump("conducting_queen","eligible");raw_state("conducting_queen",raw_full)
   try:
    queen=queen_receipt_for_forecast(frame=frame,cycle=full,forecast=raw_full,feature=full_feature,now_ms=int(now_ms))
    gated=apply_queen_gate(raw_full,queen)
    if _decision(gated)!=_decision(raw_full):
     bump("conducting_queen","diverged")
     ff=_row(gated,venue=venue,world_hash=frame.world_state_hash,path="QUEEN_GATED",entry_price=feature.price)
     bf=_row(raw_full,venue=venue,world_hash=frame.world_state_hash,path="QUEEN_BLIND",entry_price=feature.price)
     opportunity=_hash({"world":frame.world_state_hash,"organ":"conducting_queen","model":freeze.model_id,
      "horizon":int(raw_full.horizon_seconds)})
     r=freeze_post_cognition_pair(data_store=data_store,builder=self.builder,freeze=freeze,
      organ_id="conducting_queen",opportunity_id=opportunity,frame=frame,
      full_forecast=ff,ablated_forecast=bf,full_observation=entry,ablated_observation=entry,
      intervention_receipt=queen.to_dict(),frozen_at_ms=int(now_ms),
      research_campaign_id=research_campaign_id,research_target_id=research_target_id)
     if r.get("created"):bump("conducting_queen","frozen")
     else:bump("conducting_queen","skipped")
    else:bump("conducting_queen","skipped")
   except Exception:
    bump("conducting_queen","errors")
  return out
