"""Settle an adversarial shadow bundle against one public observation tape."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any,Mapping,Sequence
from .adversarial_shadow import AdversarialShadowBundle
from .shadow_flight import ShadowSettlementEngine
from .shadow_models import ShadowSettlement

@dataclass(frozen=True)
class AdversarialControlSettlement:
 control_id:str
 control_type:str
 status:str
 net_return_bps:float
 profitable_after_costs:bool
 execution_wired:bool=False
 live_eligible:bool=False

@dataclass(frozen=True)
class AdversarialBundleSettlement:
 bundle_id:str
 candidate:ShadowSettlement|None
 controls:tuple[AdversarialControlSettlement,...]
 execution_wired:bool=False
 live_eligible:bool=False

def _counterfactual_intent(candidate:Mapping[str,Any],direction:str,control_id:str)->dict[str,Any]:
 d=dict(candidate);d["shadow_intent_id"]=control_id;d["forecast_id"]="control:"+control_id;d["direction"]=direction
 d["side"]="buy" if direction=="UP" else "sell"
 # Market execution gives direction controls the same entry/exit opportunity.
 d["order_policy"]="market";d["order_type"]="market";d["time_in_force"]="IOC";d["limit_price"]=None
 return d

def settle_adversarial_bundle(*,bundle:AdversarialShadowBundle,engine:ShadowSettlementEngine,observations:Sequence[Mapping[str,Any]],settled_ts:float)->AdversarialBundleSettlement:
 base=bundle.candidate.to_dict()
 cand=engine.settle(base,observations,settled_ts=settled_ts)
 out=[]
 for ctl in bundle.controls:
  if ctl.control_type=="NO_TRADE":
   out.append(AdversarialControlSettlement(ctl.control_id,ctl.control_type,"SETTLED_NO_TRADE",0.0,False));continue
  tape=observations
  intent=_counterfactual_intent(base,str(ctl.direction),ctl.control_id)
  if ctl.control_type=="TIME_SHIFT_PLACEBO":
   shift=float(ctl.metadata.get("shift_seconds",0.0));intent["created_ts"]=float(base["created_ts"])+shift;intent["target_ts"]=float(base["target_ts"])+shift
  s=engine.settle(intent,tape,settled_ts=settled_ts)
  if s is None:
   out.append(AdversarialControlSettlement(ctl.control_id,ctl.control_type,"UNSETTLED",0.0,False))
  else:
   out.append(AdversarialControlSettlement(ctl.control_id,ctl.control_type,s.status,s.net_return_bps,s.profitable_after_costs))
 return AdversarialBundleSettlement(bundle.bundle_id,cand,tuple(out))
