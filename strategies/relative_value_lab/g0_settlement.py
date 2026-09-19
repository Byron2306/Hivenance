"""Paired settlement accounting for G0 organ ablations.

Economic usefulness is earned only from outcomes paired on the same frozen
world/opportunity. Historical and prospective evidence remain distinct.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass
from statistics import mean
from typing import Any,Iterable,Mapping

@dataclass(frozen=True)
class G0PairedOutcome:
 organ_id:str; evidence_class:str; opportunity_id:str; world_state_hash:str
 full_net_bps:float; ablated_net_bps:float
 full_acted:bool=True; ablated_acted:bool=True
 research_campaign_id:str|None=None; research_target_id:str|None=None
 execution_eligible:bool=False; promotion_eligible:bool=False
 @property
 def delta_bps(self)->float: return float(self.full_net_bps)-float(self.ablated_net_bps)
 def to_dict(self)->dict[str,Any]:
  payload=asdict(self)
  payload["delta_bps"]=self.delta_bps
  return payload

@dataclass(frozen=True)
class G0EconomicVerdict:
 organ_id:str; evidence_class:str; paired_n:int; mean_delta_bps:float
 positive_pairs:int; negative_pairs:int; zero_pairs:int; classification:str
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self)->dict[str,Any]: return asdict(self)

class G0SettlementBook:
 def __init__(self)->None:self._rows:list[G0PairedOutcome]=[]
 def add(self,row:G0PairedOutcome)->None:
  if row.evidence_class not in {"HISTORICAL","PROSPECTIVE"}: raise ValueError("invalid_evidence_class")
  if not row.world_state_hash.startswith("sha256:"): raise ValueError("world_state_hash_required")
  if any(x.organ_id==row.organ_id and x.evidence_class==row.evidence_class and x.opportunity_id==row.opportunity_id for x in self._rows):
   raise ValueError("duplicate_paired_outcome")
  self._rows.append(row)
 def verdict(self,organ_id:str,evidence_class:str)->G0EconomicVerdict:
  rows=[x for x in self._rows if x.organ_id==organ_id and x.evidence_class==evidence_class]
  ds=[x.delta_bps for x in rows];m=mean(ds) if ds else 0.0
  # This is intentionally descriptive, not a significance/promotion test.
  cls="INFLUENTIAL"
  if rows and m>0: cls="HISTORICALLY_USEFUL" if evidence_class=="HISTORICAL" else "PROSPECTIVELY_USEFUL"
  return G0EconomicVerdict(organ_id,evidence_class,len(rows),m,
   sum(x>0 for x in ds),sum(x<0 for x in ds),sum(x==0 for x in ds),cls,False,False)
 def rows(self)->tuple[G0PairedOutcome,...]:return tuple(self._rows)
