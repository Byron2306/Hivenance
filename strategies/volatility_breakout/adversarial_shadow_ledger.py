"""Durable research-only custody for adversarial shadow court settlements."""
from __future__ import annotations
import hashlib,json,sqlite3,time
from pathlib import Path
from typing import Any
from .adversarial_shadow_settlement import AdversarialBundleSettlement

def _json(x:Any)->str:return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def _sha(x:Any)->str:return "sha256:"+hashlib.sha256(_json(x).encode()).hexdigest()

class AdversarialShadowLedger:
 def __init__(self,path:str|Path="data/hivenance_adversarial_shadow.db")->None:
  self.conn=sqlite3.connect(str(path));self.conn.row_factory=sqlite3.Row
  self.conn.execute("""CREATE TABLE IF NOT EXISTS court_settlement(
   receipt_id TEXT PRIMARY KEY,bundle_id TEXT NOT NULL,settled_ts REAL NOT NULL,
   payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
   authority TEXT NOT NULL,execution_eligible INTEGER NOT NULL DEFAULT 0,
   promotion_eligible INTEGER NOT NULL DEFAULT 0,inserted_ts_ms INTEGER NOT NULL)""");self.conn.commit()
 def persist(self,settlement:AdversarialBundleSettlement,*,settled_ts:float)->str:
  payload={"bundle_id":settlement.bundle_id,
   "candidate":settlement.candidate.to_dict() if settlement.candidate else None,
   "controls":[{"control_id":x.control_id,"control_type":x.control_type,"status":x.status,"net_return_bps":x.net_return_bps,"profitable_after_costs":x.profitable_after_costs} for x in settlement.controls],
   "execution_wired":False,"live_eligible":False}
  rid=_sha(payload)
  self.conn.execute("INSERT OR IGNORE INTO court_settlement VALUES(?,?,?,?,?,?,?,?,?)",(rid,settlement.bundle_id,float(settled_ts),_json(payload),_sha(payload),"PROSPECTIVE_SHADOW_RESEARCH_ONLY",0,0,int(time.time()*1000)));self.conn.commit();return rid
 def receipts(self)->list[dict[str,Any]]:
  out=[]
  for r in self.conn.execute("SELECT * FROM court_settlement ORDER BY settled_ts"):
   d=dict(r);d["payload"]=json.loads(d.pop("payload_json"));out.append(d)
  return out
 def close(self):self.conn.close()
