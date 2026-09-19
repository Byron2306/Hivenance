"""Convert evidence-resolved Queen obligations into qualified learning receipts."""
from __future__ import annotations
from hashlib import sha256
import json
from typing import Any
from .research_obligation_lifecycle import ResearchObligationRecord

def obligation_learning_receipt(r:ResearchObligationRecord,*,created_at_ms:int)->dict[str,Any]:
 if r.state not in {"ANSWERED","FALSIFIED"}: raise ValueError("terminal_evidence_bound_obligation_required")
 if not r.evidence_roots: raise ValueError("resolved_obligation_missing_evidence")
 body={"obligation_id":r.obligation_id,"state":r.state,"action":r.action,"target":r.target,
       "answer":r.answer,"evidence_roots":r.evidence_roots,"source_learning_ids":r.source_learning_ids}
 lid="obligation:"+sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()
 return {"schema":"hivenance_research_obligation_learning_v1","learning_id":lid,
  "status":"RESEARCH_OBLIGATION_"+r.state,"authority":"PROSPECTIVE_RESEARCH_ONLY",
  "created_at_ms":int(created_at_ms),"source_obligation_id":r.obligation_id,
  "source_learning_ids":list(r.source_learning_ids),"action":r.action,"target":r.target,
  "answer":r.answer,"outcome":r.state,
  "source_artifacts":[{"sha256":x.split(":",1)[-1]} for x in r.evidence_roots],
  "execution_eligible":False,"promotion_eligible":False,
  "interpretation":{"supported":f"{r.target}: {r.answer}"} if r.state=="ANSWERED" else
                   {"weakened":f"{r.target}: {r.answer}"}}
