"""End-to-end G0 research experiment runner.

Freezes the experiment, runs same-world organ ablations, binds externally settled
paired post-cost outcomes, and persists authority-closed receipts. This runner
never manufactures market outcomes and never grants execution authority.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass
from typing import Any,Mapping,Sequence
from .g0_freeze import G0Freeze,freeze_g0
from .g0_receipts import G0ReceiptLedger
from .g0_settlement import G0PairedOutcome,G0SettlementBook
from .synthesis_gauntlet import G0_ORGANS,SynthesisGauntlet

@dataclass(frozen=True)
class G0ExperimentResult:
 freeze:G0Freeze
 ablation:Mapping[str,Any]
 economic_verdicts:tuple[Mapping[str,Any],...]
 receipt_ids:tuple[str,...]
 execution_eligible:bool=False
 promotion_eligible:bool=False
 def to_dict(self)->dict[str,Any]:return asdict(self)

class G0ExperimentRunner:
 def __init__(self,*,ledger:G0ReceiptLedger,gauntlet:SynthesisGauntlet|None=None)->None:
  self.ledger=ledger;self.gauntlet=gauntlet or SynthesisGauntlet()

 def run(self,*,created_at_ms:int,config:Mapping[str,Any],
         paired_outcomes:Sequence[G0PairedOutcome]=(),
         organs:Sequence[str]=G0_ORGANS,**runtime_inputs:Any)->G0ExperimentResult:
  freeze=freeze_g0(created_at_ms=created_at_ms,organs=organs,config=config)
  report=self.gauntlet.run(organs=organs,**runtime_inputs)
  ids=[self.ledger.persist(kind="FREEZE",world_state_hash=report.world_state_hash,
    payload=freeze.to_dict(),created_at_ms=created_at_ms)]
  ids.append(self.ledger.persist_ablation(report,created_at_ms=created_at_ms))
  book=G0SettlementBook()
  for row in paired_outcomes:
   if row.world_state_hash!=report.world_state_hash:raise ValueError("paired_outcome_world_mismatch")
   if row.organ_id not in organs:raise ValueError("paired_outcome_unknown_organ")
   book.add(row)
  verdicts=[]
  for organ in organs:
   for kind in ("HISTORICAL","PROSPECTIVE"):
    rows=[x for x in book.rows() if x.organ_id==organ and x.evidence_class==kind]
    if not rows:continue
    v=book.verdict(organ,kind);verdicts.append(v.to_dict())
    ids.append(self.ledger.persist_economic(v,world_state_hash=report.world_state_hash,created_at_ms=created_at_ms))
  return G0ExperimentResult(freeze,report.to_dict(),tuple(verdicts),tuple(ids),False,False)
