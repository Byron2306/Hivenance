"""Bind real custodied/graph evidence to Queen research obligations."""
from __future__ import annotations
from typing import Iterable
from agents.public_microstructure_observer import CustodiedMicrostructure
from .research_obligation_lifecycle import ResearchObligationLifecycle,ResearchObligationRecord
from .world_graph import WorldGraphNode

def attach_microstructure(r:ResearchObligationRecord,m:CustodiedMicrostructure)->ResearchObligationRecord:
 if r.organ_id not in {"public_observer","edge_ecology"}: raise ValueError("obligation_not_microstructure_owned")
 return ResearchObligationLifecycle().attach_evidence(r,m.trade_payload_sha256,m.book_payload_sha256)

def attach_graph_nodes(r:ResearchObligationRecord,nodes:Iterable[WorldGraphNode])->ResearchObligationRecord:
 roots=tuple(dict.fromkeys(root for n in nodes for root in n.evidence_roots))
 if not roots: raise ValueError("graph_nodes_have_no_evidence_roots")
 return ResearchObligationLifecycle().attach_evidence(r,*roots)
