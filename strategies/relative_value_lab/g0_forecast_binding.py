"""Bind genuine Phoenix forecasts to G0 cognition without inventing alpha."""
from __future__ import annotations
from typing import Any,Mapping
from strategies.volatility_breakout.shadow_flight import ShadowIntentBuilder
from .synthesis_influence import measure_influence
from .g0_prospective_opportunity import freeze_prospective_opportunity
from .g0_no_trade import no_trade_intent

def _forecast_row(x:Any)->dict[str,Any]:
 if hasattr(x,"to_dict"):return dict(x.to_dict())
 if hasattr(x,"__dataclass_fields__"):
  from dataclasses import asdict
  return asdict(x)
 return dict(x)

def freeze_forecast_pair(*,data_store:Any,builder:ShadowIntentBuilder,freeze:Any,
 organ_id:str,opportunity_id:str,frame:Any,full_cycle:Any,ablated_cycle:Any,
 full_forecast:Mapping[str,Any],ablated_forecast:Mapping[str,Any],
 full_observation:Mapping[str,Any],ablated_observation:Mapping[str,Any],
 frozen_at_ms:int)->dict[str,Any]:
 """Use Phoenix's existing builder on two independently produced forecasts."""
 inf=measure_influence(organ_id=organ_id,full=full_cycle,ablated=ablated_cycle)
 if not inf.cognition_changed:raise ValueError("organ_did_not_change_cognition")
 ff=_forecast_row(full_forecast);af=_forecast_row(ablated_forecast)
 if ff.get("abstain") and af.get("abstain"):raise ValueError("paired_shadow_both_abstain")
 if str(ff.get("symbol") or "")!=str(af.get("symbol") or ""):raise ValueError("paired_forecast_symbol_mismatch")
 if int(ff.get("horizon_seconds") or 0)!=int(af.get("horizon_seconds") or 0):raise ValueError("paired_forecast_horizon_mismatch")
 full_intent=(no_trade_intent(forecast=ff,reason=str(ff.get("reason") or "ABSTAIN")) if ff.get("abstain") else builder.build(ff,full_observation,freeze).to_dict())
 blind_intent=(no_trade_intent(forecast=af,reason=str(af.get("reason") or "ABSTAIN")) if af.get("abstain") else builder.build(af,ablated_observation,freeze).to_dict())
 return freeze_prospective_opportunity(data_store=data_store,organ_id=organ_id,
  opportunity_id=opportunity_id,frame=frame,full_cycle=full_cycle,ablated_cycle=ablated_cycle,
  full_intent=full_intent,ablated_intent=blind_intent,frozen_at_ms=frozen_at_ms)
