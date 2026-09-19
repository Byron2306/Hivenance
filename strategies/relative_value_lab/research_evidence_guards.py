"""Evidence qualification guards for temporal and lineage obligations."""
from __future__ import annotations
from dataclasses import dataclass
from .research_obligation_lifecycle import ResearchObligationLifecycle,ResearchObligationRecord

@dataclass(frozen=True)
class TemporalEvidence:
 evidence_root:str; observed_from_ms:int; observed_through_ms:int
 def __post_init__(self):
  if not self.evidence_root.startswith("sha256:"): raise ValueError("immutable_evidence_root_required")
  if self.observed_through_ms<self.observed_from_ms: raise ValueError("invalid_temporal_window")

@dataclass(frozen=True)
class LineageEvidence:
 evidence_root:str; lineage_id:str; source_id:str
 def __post_init__(self):
  if not self.evidence_root.startswith("sha256:"): raise ValueError("immutable_evidence_root_required")
  if not self.lineage_id or not self.source_id: raise ValueError("lineage_identity_required")

def attach_temporal_horizon(r:ResearchObligationRecord,e:TemporalEvidence,*,required_through_ms:int)->ResearchObligationRecord:
 if r.organ_id!="temporal_observer" or r.family!="TEMPORAL": raise ValueError("obligation_not_temporal_owned")
 if e.observed_through_ms<int(required_through_ms): raise ValueError("future_horizon_incomplete")
 return ResearchObligationLifecycle().attach_evidence(r,e.evidence_root)

def attach_independent_lineage(r:ResearchObligationRecord,e:LineageEvidence,*,challenged_lineage_ids:tuple[str,...],challenged_source_ids:tuple[str,...])->ResearchObligationRecord:
 if r.organ_id!="lineage_guard" or r.family!="LINEAGE": raise ValueError("obligation_not_lineage_owned")
 if e.lineage_id in challenged_lineage_ids: raise ValueError("same_lineage_not_independent")
 if e.source_id in challenged_source_ids: raise ValueError("same_source_not_independent")
 return ResearchObligationLifecycle().attach_evidence(r,e.evidence_root)
