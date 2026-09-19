"""Canonical persistence seam for sealed G0 prospective shadow twins."""
from __future__ import annotations
import hashlib,json,time
from typing import Any,Mapping

AUTHORITY="SYNTHESIS_G0_PROSPECTIVE_SHADOW_ONLY"
def _json(x:Any)->str:return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def _hash(x:Any)->str:return "sha256:"+hashlib.sha256(_json(x).encode()).hexdigest()

def ensure_g0_twin_schema(data_store:Any)->None:
 if not getattr(data_store,"conn",None):raise ValueError("data_store_unavailable")
 with data_store._lock:
  data_store.conn.execute("""CREATE TABLE IF NOT EXISTS phase5_g0_shadow_twins(
   twin_freeze_id TEXT PRIMARY KEY,organ_id TEXT NOT NULL,opportunity_id TEXT NOT NULL,
   world_state_hash TEXT NOT NULL,frozen_at_ms INTEGER NOT NULL,target_ts REAL NOT NULL,
   status TEXT NOT NULL DEFAULT 'FROZEN',authority TEXT NOT NULL,
   execution_eligible INTEGER NOT NULL DEFAULT 0,promotion_eligible INTEGER NOT NULL DEFAULT 0,
   payload_sha256 TEXT NOT NULL,payload TEXT NOT NULL)""")
  data_store.conn.execute("CREATE INDEX IF NOT EXISTS idx_phase5_g0_twins_target ON phase5_g0_shadow_twins(status,target_ts)")
  data_store.conn.execute("""CREATE TABLE IF NOT EXISTS phase5_g0_shadow_twin_settlements(
   twin_freeze_id TEXT PRIMARY KEY,settled_ts REAL NOT NULL,payload_sha256 TEXT NOT NULL,
   authority TEXT NOT NULL,execution_eligible INTEGER NOT NULL DEFAULT 0,
   promotion_eligible INTEGER NOT NULL DEFAULT 0,payload TEXT NOT NULL)""")
  data_store.conn.commit()

def persist_frozen_twin(data_store:Any,twin:Any)->bool:
 ensure_g0_twin_schema(data_store);p=twin.to_dict() if hasattr(twin,"to_dict") else dict(twin)
 if p.get("authority")!=AUTHORITY or p.get("execution_eligible") is not False or p.get("promotion_eligible") is not False:
  raise ValueError("g0_twin_authority_invalid")
 if float(p["target_ts"])<=float(p["frozen_at_ms"])/1000.0:raise ValueError("g0_twin_not_frozen_before_target")
 raw=_json(p)
 with data_store._lock:
  cur=data_store.conn.execute("INSERT OR IGNORE INTO phase5_g0_shadow_twins VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
   (p["twin_freeze_id"],p["organ_id"],p["opportunity_id"],p["world_state_hash"],int(p["frozen_at_ms"]),
    float(p["target_ts"]),"FROZEN",AUTHORITY,0,0,_hash(p),raw));data_store.conn.commit();return cur.rowcount>0

def mature_frozen_twins(data_store:Any,*,now_ts:float)->tuple[dict[str,Any],...]:
 ensure_g0_twin_schema(data_store)
 with data_store._lock:
  cur=data_store.conn.execute("SELECT payload FROM phase5_g0_shadow_twins WHERE status='FROZEN' AND target_ts<=? ORDER BY target_ts",(float(now_ts),))
  return tuple(json.loads(r[0]) for r in cur.fetchall())

def persist_twin_settlement(data_store:Any,*,twin_freeze_id:str,payload:Mapping[str,Any],settled_ts:float)->bool:
 ensure_g0_twin_schema(data_store);body=dict(payload)
 if body.get("execution_eligible") is not False or body.get("promotion_eligible") is not False:raise ValueError("g0_twin_settlement_authority_escalation")
 raw=_json(body)
 with data_store._lock:
  cur=data_store.conn.execute("INSERT OR IGNORE INTO phase5_g0_shadow_twin_settlements VALUES(?,?,?,?,?,?,?)",
   (twin_freeze_id,float(settled_ts),_hash(body),AUTHORITY,0,0,raw))
  data_store.conn.execute("UPDATE phase5_g0_shadow_twins SET status='SETTLED' WHERE twin_freeze_id=?",(twin_freeze_id,))
  data_store.conn.commit();return cur.rowcount>0
