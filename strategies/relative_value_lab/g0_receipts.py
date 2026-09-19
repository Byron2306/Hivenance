"""Durable, content-addressed G0 research receipts."""
from __future__ import annotations
import hashlib,json,sqlite3
from typing import Any,Mapping
from .g0_settlement import G0EconomicVerdict

AUTHORITY="SYNTHESIS_G0_RESEARCH_ONLY"

def _json(v:Any)->str:return json.dumps(v,sort_keys=True,separators=(",",":"),default=str)
def _hash(v:Any)->str:return "sha256:"+hashlib.sha256(_json(v).encode()).hexdigest()

class G0ReceiptLedger:
 def __init__(self,path:str="data/hivenance_synthesis_g0.db")->None:
  self.conn=sqlite3.connect(path)
  self.conn.execute("""CREATE TABLE IF NOT EXISTS g0_receipts(
   receipt_id TEXT PRIMARY KEY, created_at_ms INTEGER NOT NULL, kind TEXT NOT NULL,
   world_state_hash TEXT NOT NULL, payload_sha256 TEXT NOT NULL, authority TEXT NOT NULL,
   execution_eligible INTEGER NOT NULL DEFAULT 0,promotion_eligible INTEGER NOT NULL DEFAULT 0,
   payload TEXT NOT NULL)""")
  self.conn.commit()
 def persist(self,*,kind:str,world_state_hash:str,payload:Mapping[str,Any],created_at_ms:int)->str:
  if not world_state_hash.startswith("sha256:"):raise ValueError("world_state_hash_required")
  body={"kind":kind,"world_state_hash":world_state_hash,"payload":dict(payload),
   "authority":AUTHORITY,"execution_eligible":False,"promotion_eligible":False}
  rid=_hash(body);raw=_json(body)
  self.conn.execute("INSERT OR IGNORE INTO g0_receipts VALUES(?,?,?,?,?,?,?,?,?)",
   (rid,int(created_at_ms),kind,world_state_hash,_hash(body["payload"]),AUTHORITY,0,0,raw))
  self.conn.commit();return rid
 def persist_ablation(self,report:Any,*,created_at_ms:int)->str:
  return self.persist(kind="ABLATION",world_state_hash=report.world_state_hash,
   payload=report.to_dict(),created_at_ms=created_at_ms)
 def persist_economic(self,verdict:G0EconomicVerdict,*,world_state_hash:str,created_at_ms:int)->str:
  return self.persist(kind="ECONOMIC_"+verdict.evidence_class,world_state_hash=world_state_hash,
   payload=verdict.to_dict(),created_at_ms=created_at_ms)
 def rows(self)->tuple[dict[str,Any],...]:
  cur=self.conn.execute("SELECT receipt_id,payload FROM g0_receipts ORDER BY created_at_ms,receipt_id")
  return tuple({"receipt_id":r,"payload":json.loads(p)} for r,p in cur.fetchall())
 def close(self)->None:self.conn.close()
