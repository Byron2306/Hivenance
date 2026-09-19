"""Prospective FULL_HIVE vs organ-blind shadow twins.

Twins must be supplied as independently frozen intents produced by the two
cognition paths. Both are settled by the same Phoenix engine on the exact same
future public observation tape. No synthetic direction mutation is allowed.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from typing import Any,Mapping,Sequence
from .g0_settlement import G0PairedOutcome
from .g0_no_trade import no_trade_settlement

@dataclass(frozen=True)
class G0ShadowTwin:
 organ_id:str; opportunity_id:str; world_state_hash:str
 full_intent:Mapping[str,Any]; ablated_intent:Mapping[str,Any]
 execution_eligible:bool=False; promotion_eligible:bool=False

@dataclass(frozen=True)
class G0ShadowTwinSettlement:
 organ_id:str; opportunity_id:str; world_state_hash:str
 full_settlement:Mapping[str,Any]; ablated_settlement:Mapping[str,Any]
 paired_outcome:G0PairedOutcome
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self):
  payload=asdict(self)
  payload["paired_outcome"]=self.paired_outcome.to_dict()
  return payload

def settle_shadow_twin(*,twin:G0ShadowTwin,settler:Any,
                       observations:Sequence[Mapping[str,Any]],settled_ts:float)->G0ShadowTwinSettlement:
 if not twin.world_state_hash.startswith("sha256:"):raise ValueError("world_state_hash_required")
 if not observations:raise ValueError("shared_future_tape_required")
 for label,intent in (("full",twin.full_intent),("ablated",twin.ablated_intent)):
  if bool(intent.get("live_eligible")) or bool(intent.get("execution_wired")):
   raise ValueError(label+"_intent_execution_authority_forbidden")
  if str(intent.get("transmission_status") or "NEVER_TRANSMITTED")!="NEVER_TRANSMITTED":
   raise ValueError(label+"_intent_was_transmitted")
 full=(no_trade_settlement(twin.full_intent,settled_ts=settled_ts) if twin.full_intent.get("g0_no_trade") else settler.settle(twin.full_intent,observations,settled_ts=settled_ts))
 blind=(no_trade_settlement(twin.ablated_intent,settled_ts=settled_ts) if twin.ablated_intent.get("g0_no_trade") else settler.settle(twin.ablated_intent,observations,settled_ts=settled_ts))
 if full is None or blind is None:raise ValueError("twin_not_yet_settleable")
 fd=full.to_dict() if hasattr(full,"to_dict") else dict(full)
 bd=blind.to_dict() if hasattr(blind,"to_dict") else dict(blind)
 pair=G0PairedOutcome(twin.organ_id,"PROSPECTIVE",twin.opportunity_id,twin.world_state_hash,
  float(fd.get("net_return_bps") or 0.0),float(bd.get("net_return_bps") or 0.0),
  str(fd.get("status")) not in {"MISSED_FILL","ABSTAIN_NO_TRADE"},
  str(bd.get("status")) not in {"MISSED_FILL","ABSTAIN_NO_TRADE"})
 return G0ShadowTwinSettlement(twin.organ_id,twin.opportunity_id,twin.world_state_hash,fd,bd,pair,False,False)
