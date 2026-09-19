"""Freeze causal post-cognition forecast interventions such as PolyphonicQuorum."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict
from typing import Any,Mapping
from .g0_no_trade import no_trade_intent
from .g0_twin_freeze import FrozenG0Twin
from .g0_twin_store import persist_frozen_twin

def _hash(x:Any)->str:
 return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def _row(x:Any)->dict[str,Any]:
 return asdict(x) if hasattr(x,"__dataclass_fields__") else dict(x)

def freeze_post_cognition_pair(*,data_store:Any,builder:Any,freeze:Any,organ_id:str,
 opportunity_id:str,frame:Any,full_forecast:Mapping[str,Any],ablated_forecast:Mapping[str,Any],
 full_observation:Mapping[str,Any],ablated_observation:Mapping[str,Any],intervention_receipt:Mapping[str,Any],
 frozen_at_ms:int,research_campaign_id:str|None=None,research_target_id:str|None=None)->dict[str,Any]:
 ff=_row(full_forecast);af=_row(ablated_forecast)
 if str(ff.get("symbol") or "")!=str(af.get("symbol") or ""):raise ValueError("paired_forecast_symbol_mismatch")
 if int(ff.get("horizon_seconds") or 0)!=int(af.get("horizon_seconds") or 0):raise ValueError("paired_forecast_horizon_mismatch")
 if (bool(ff.get("abstain")),ff.get("direction"),ff.get("expected_net_bps")) == (bool(af.get("abstain")),af.get("direction"),af.get("expected_net_bps")):
  raise ValueError("post_cognition_intervention_did_not_change_forecast")
 if intervention_receipt.get("execution_eligible") is not False or intervention_receipt.get("promotion_eligible") is not False:
  raise ValueError("post_cognition_intervention_authority_invalid")
 full_intent=(no_trade_intent(forecast=ff,reason=str(ff.get("reason") or "ABSTAIN")) if ff.get("abstain")
  else builder.build(ff,full_observation,freeze).to_dict())
 blind_intent=(no_trade_intent(forecast=af,reason=str(af.get("reason") or "ABSTAIN")) if af.get("abstain")
  else builder.build(af,ablated_observation,freeze).to_dict())
 target_ts=float(ff.get("target_ts") or ff.get("target_timestamp_ms",0)/1000.0)
 body={"organ_id":organ_id,"opportunity_id":opportunity_id,"world":frame.world_state_hash,
  "full_forecast":ff,"ablated_forecast":af,"intervention_receipt":dict(intervention_receipt)}
 receipt_hash=_hash(body)
 twin=FrozenG0Twin(
  twin_freeze_id="g0post_"+receipt_hash.split(":",1)[1][:24],organ_id=str(organ_id),
  opportunity_id=str(opportunity_id),world_state_id=frame.world_state_id,world_state_hash=frame.world_state_hash,
  frozen_at_ms=int(frozen_at_ms),target_ts=target_ts,
  full_cycle_id="post:"+receipt_hash[-16:],ablated_cycle_id="blind:"+receipt_hash[-16:],
  full_cognition_hash=receipt_hash,ablated_cognition_hash=_hash({"blind":organ_id,"world":frame.world_state_hash}),
  full_intent=full_intent,ablated_intent=blind_intent,
  research_campaign_id=research_campaign_id,research_target_id=research_target_id)
 created=persist_frozen_twin(data_store,twin)
 return {"created":created,"twin_freeze_id":twin.twin_freeze_id,"receipt_hash":receipt_hash,
  "research_campaign_id":research_campaign_id,"research_target_id":research_target_id,
  "execution_eligible":False,"promotion_eligible":False}
