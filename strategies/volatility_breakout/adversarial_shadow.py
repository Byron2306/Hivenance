"""Adversarial companions for existing Phoenix shadow intents.

Controls are research counterfactuals only. They never acquire transmission or
live-execution authority.
"""
from __future__ import annotations
import hashlib,json
from dataclasses import dataclass,asdict
from typing import Any,Mapping
from .shadow_models import ShadowOrderIntent

def _id(x:Any)->str:
 return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

@dataclass(frozen=True)
class AdversarialShadowControl:
 control_id:str
 parent_shadow_intent_id:str
 control_type:str
 symbol:str
 direction:str|None
 created_ts:float
 target_ts:float
 metadata:Mapping[str,Any]
 transmission_status:str="NEVER_TRANSMITTED"
 execution_wired:bool=False
 live_eligible:bool=False
 def to_dict(self): return asdict(self)

@dataclass(frozen=True)
class AdversarialShadowBundle:
 bundle_id:str
 candidate:ShadowOrderIntent
 controls:tuple[AdversarialShadowControl,...]
 execution_wired:bool=False
 live_eligible:bool=False

class AdversarialShadowCourt:
 CONTROL_TYPES=("NO_TRADE","SIGN_INVERTED","DETERMINISTIC_RANDOM","TIME_SHIFT_PLACEBO")
 def build(self,intent:ShadowOrderIntent)->AdversarialShadowBundle:
  base={"parent":intent.shadow_intent_id,"symbol":intent.symbol,"created":intent.created_ts,"target":intent.target_ts}
  opposite="DOWN" if intent.direction=="UP" else "UP"
  rnd="UP" if int(_id({**base,"kind":"random"})[:8],16)%2==0 else "DOWN"
  span=max(1.0,intent.target_ts-intent.created_ts)
  specs=[
   ("NO_TRADE",None,{}),
   ("SIGN_INVERTED",opposite,{}),
   ("DETERMINISTIC_RANDOM",rnd,{"seed_digest":_id({**base,"kind":"random"})}),
   ("TIME_SHIFT_PLACEBO",intent.direction,{"shift_seconds":span}),
  ]
  controls=tuple(AdversarialShadowControl(_id({**base,"type":k,"direction":d,"meta":m}),intent.shadow_intent_id,k,intent.symbol,d,intent.created_ts,intent.target_ts,m) for k,d,m in specs)
  return AdversarialShadowBundle(_id({"candidate":intent.shadow_intent_id,"controls":[x.control_id for x in controls]}),intent,controls)
