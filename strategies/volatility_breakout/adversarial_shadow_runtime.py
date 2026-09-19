"""Canonical Phase-5 runtime bridge for adversarial Shadow Court."""
from __future__ import annotations
import json
from typing import Any,Mapping,Sequence
from .adversarial_shadow import AdversarialShadowCourt
from .adversarial_shadow_settlement import settle_adversarial_bundle
from .adversarial_shadow_learning import adversarial_learning_receipt
from .shadow_models import ShadowOrderIntent

def _intent(row:Mapping[str,Any])->ShadowOrderIntent:
 p=row.get("payload")
 if isinstance(p,str): p=json.loads(p)
 d=dict(p if isinstance(p,Mapping) else row)
 fields=ShadowOrderIntent.__dataclass_fields__
 return ShadowOrderIntent(**{k:d[k] for k in fields if k in d})

def prosecute_settled_shadow(*,data_store:Any,settler:Any,intent_row:Mapping[str,Any],observations:Sequence[Mapping[str,Any]],settled_ts:float)->dict[str,Any]:
 intent=_intent(intent_row)
 bundle=AdversarialShadowCourt().build(intent)
 settlement=settle_adversarial_bundle(bundle=bundle,engine=settler,observations=observations,settled_ts=settled_ts)
 learning=adversarial_learning_receipt(settlement)
 receipt={"receipt_id":"shadow:"+bundle.bundle_id,"bundle_id":bundle.bundle_id,"settled_ts":float(settled_ts),
          "settlement":{"candidate":settlement.candidate.to_dict() if settlement.candidate else None,
          "controls":[x.__dict__ for x in settlement.controls]},"learning":learning,
          "authority":"PROSPECTIVE_SHADOW_RESEARCH_ONLY","execution_eligible":False,"promotion_eligible":False}
 created=data_store.persist_phase5_adversarial_shadow_receipt(receipt)
 return {"created":bool(created),"bundle_id":bundle.bundle_id,"learning":learning,
         "execution_eligible":False,"promotion_eligible":False}
