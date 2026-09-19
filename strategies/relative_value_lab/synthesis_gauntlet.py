"""G0 same-world organ murder chamber for research cognition."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from typing import Any,Mapping,Sequence
from .synthesis_runtime import SynthesisRuntime
from .synthesis_influence import InfluenceReceipt,measure_influence

G0_ORGANS=("horizon_context","edge_ecology","temporal_participation_bee","learning_memory","comparison_engine")

@dataclass(frozen=True)
class G0OrganVerdict:
 organ_id:str
 classification:str
 invocation_state:str
 cognition_changed:bool
 influence:Mapping[str,Any]
 execution_eligible:bool=False
 promotion_eligible:bool=False
 def to_dict(self): return asdict(self)

@dataclass(frozen=True)
class G0AblationReport:
 schema:str
 world_state_id:str
 world_state_hash:str
 full_cycle_id:str
 verdicts:tuple[G0OrganVerdict,...]
 execution_eligible:bool=False
 promotion_eligible:bool=False
 def to_dict(self): return asdict(self)

class SynthesisGauntlet:
 def __init__(self,runtime:SynthesisRuntime|None=None)->None:
  self.runtime=runtime or SynthesisRuntime()

 def run(self,*,organs:Sequence[str]=G0_ORGANS,**inputs:Any)->G0AblationReport:
  if inputs.get("disabled_organs"): raise ValueError("gauntlet_owns_ablation_mask")
  full=self.runtime.run(**inputs)
  by={r.organ_id:r for r in full.organ_receipts}
  verdicts=[]
  for organ in organs:
   base=by.get(organ)
   invocation=base.state if base else "UNAVAILABLE"
   if base is None:
    verdicts.append(G0OrganVerdict(organ,"UNAVAILABLE",invocation,False,{}));continue
   if invocation!="INVOKED":
    verdicts.append(G0OrganVerdict(organ,"AVAILABLE",invocation,False,{}));continue
   blind=self.runtime.run(**inputs,disabled_organs=(organ,))
   inf=measure_influence(organ_id=organ,full=full,ablated=blind)
   classification="INFLUENTIAL" if inf.cognition_changed else "INVOKED"
   verdicts.append(G0OrganVerdict(organ,classification,invocation,inf.cognition_changed,inf.to_dict()))
  return G0AblationReport("hivenance_synthesis_g0_ablation_v1",full.world_state_id,
   full.world_state_hash,full.cycle_id,tuple(verdicts),False,False)
