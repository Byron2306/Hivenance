"""Learning-receipt bridge into the World Graph.

Receipts are qualified memory, never observed market truth and never execution
authority. They are attached to one immutable world root so Queen/Triune can
inspect what the Hive has learned, its authority, limitations and next tests.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any,Mapping
from .world_graph import WorldGraph,WorldGraphNode

def add_learning_receipt(graph:WorldGraph,receipt:Mapping[str,Any],*,created_at_ms:int|None=None)->WorldGraphNode:
 if receipt.get("execution_eligible") is not False or receipt.get("promotion_eligible") is not False:
  raise ValueError("learning receipt must remain non-execution/non-promotion")
 authority=str(receipt.get("authority",""))
 if authority not in {"HISTORICAL_DISCOVERY_ONLY","PROSPECTIVE_RESEARCH_ONLY","PROSPECTIVE_SHADOW_RESEARCH_ONLY"}:
  raise ValueError("unsupported learning authority")
 rid=str(receipt.get("learning_id") or "anonymous")
 roots=[]
 for x in receipt.get("source_artifacts",[]):
  if isinstance(x,dict) and x.get("sha256"):
   h=str(x["sha256"]);roots.append(h if h.startswith("sha256:") else "sha256:"+h)
 payload=dict(receipt)
 # Use the graph's public constructor so world binding, node identity and
 # authority invariants remain centralized in WorldGraph.
 return graph.add_node(
  organ_id="LEARNING_MEMORY",family="LEARNING",
  created_at_ms=int(created_at_ms or receipt.get("created_at_ms") or graph.frame.asof_ms),
  evidence_roots=roots,lineage_id=f"learning-receipt:{rid}",
  transformation_id=str(receipt.get("schema","hivenance_learning_receipt_v1")),
  payload=payload,freshness=1.0,
  uncertainty=0.75 if authority=="HISTORICAL_DISCOVERY_ONLY" else (0.35 if authority=="PROSPECTIVE_SHADOW_RESEARCH_ONLY" else 0.5),
  synthetic=False,
 )

def load_learning_receipt(path:str|Path)->dict[str,Any]:
 return json.loads(Path(path).read_text())
