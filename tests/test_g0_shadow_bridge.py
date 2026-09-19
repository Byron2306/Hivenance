import json,pytest
from strategies.relative_value_lab.g0_shadow_bridge import load_canonical_shadow_evidence,shadow_learning_receipts

class Store:
 def __init__(self,p):self.p=p
 def get_phase5_adversarial_shadow_receipts(self,limit=250):return [{"receipt_id":"r","payload":json.dumps(self.p)}]

def receipt():
 return {"receipt_id":"shadow:b","bundle_id":"b","settled_ts":10,
 "settlement":{"candidate":{"net_return_bps":3},"controls":[{"control_type":"NO_TRADE","net_return_bps":0}]},
 "learning":{"schema":"hivenance_adversarial_shadow_learning_v1","learning_id":"shadow:b",
 "status":"PROSPECTIVE_SHADOW_EVIDENCE","authority":"PROSPECTIVE_SHADOW_RESEARCH_ONLY",
 "comparisons":{"candidate_minus_no_trade_bps":3},"unsettled_controls":[],
 "execution_eligible":False,"promotion_eligible":False,"interpretation":"comparative only"},
 "authority":"PROSPECTIVE_SHADOW_RESEARCH_ONLY","execution_eligible":False,"promotion_eligible":False}

def test_bridge_reads_canonical_shadow_custody_without_claiming_organ_usefulness():
 x=load_canonical_shadow_evidence(Store(receipt()))[0]
 assert x.candidate_net_return_bps==3 and x.controls[0]["control_type"]=="NO_TRADE"
 assert shadow_learning_receipts(Store(receipt()))[0]["learning_id"]=="shadow:b"
 assert not hasattr(x,"organ_id") and not x.execution_eligible and not x.promotion_eligible

def test_bridge_refuses_authority_escalation():
 p=receipt();p["execution_eligible"]=True
 with pytest.raises(ValueError,match="escalation"):load_canonical_shadow_evidence(Store(p))
