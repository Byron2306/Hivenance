"""Immutable pre-outcome freeze for the G1 prospective organ-utility campaign."""
from __future__ import annotations
import hashlib,json,time
from dataclasses import asdict
from typing import Any
from .g1_utility_campaign import G1CampaignPolicy

AUTHORITY="SYNTHESIS_G1_PROSPECTIVE_RESEARCH_ONLY"

def _json(x:Any)->str:return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def _hash(x:Any)->str:return "sha256:"+hashlib.sha256(_json(x).encode()).hexdigest()

def ensure_g1_campaign_schema(data_store:Any)->None:
 if not getattr(data_store,"conn",None):raise ValueError("data_store_unavailable")
 with data_store._lock:
  data_store.conn.execute("""CREATE TABLE IF NOT EXISTS g1_campaign_freeze(
   campaign_id TEXT PRIMARY KEY,created_ts REAL NOT NULL,policy_sha256 TEXT NOT NULL,
   authority TEXT NOT NULL,execution_eligible INTEGER NOT NULL DEFAULT 0,
   promotion_eligible INTEGER NOT NULL DEFAULT 0,payload TEXT NOT NULL)""")
  data_store.conn.commit()

def freeze_g1_campaign(data_store:Any,*,policy:G1CampaignPolicy,organs:tuple[str,...],
                       created_ts:float|None=None)->dict[str,Any]:
 ensure_g1_campaign_schema(data_store)
 ts=float(created_ts if created_ts is not None else time.time())
 body={"schema":"hivenance_g1_campaign_freeze_v1","created_ts":ts,
  "organs":tuple(sorted(set(str(x) for x in organs))),"policy":policy.to_dict(),
  "authority":AUTHORITY,"execution_eligible":False,"promotion_eligible":False}
 campaign_id="g1_"+_hash({"organs":body["organs"],"policy":body["policy"]}).split(":",1)[1][:24]
 body["campaign_id"]=campaign_id
 raw=_json(body);digest=_hash(body["policy"])
 with data_store._lock:
  row=data_store.conn.execute("SELECT payload FROM g1_campaign_freeze WHERE campaign_id=?",(campaign_id,)).fetchone()
  if row:
   existing=json.loads(row[0])
   if existing.get("policy")!=body["policy"] or tuple(existing.get("organs") or ())!=body["organs"]:
    raise ValueError("g1_campaign_freeze_conflict")
   return {"created":False,**existing}
  # Fail closed if a different campaign is already frozen. Changing policy requires
  # an explicit new campaign, not silent mutation of the active experiment.
  other=data_store.conn.execute("SELECT campaign_id,payload FROM g1_campaign_freeze ORDER BY created_ts LIMIT 1").fetchone()
  if other and str(other[0])!=campaign_id:
   raise ValueError("g1_campaign_already_frozen_with_different_policy")
  data_store.conn.execute("INSERT INTO g1_campaign_freeze VALUES(?,?,?,?,?,?,?)",
   (campaign_id,ts,digest,AUTHORITY,0,0,raw));data_store.conn.commit()
 return {"created":True,**body}

def get_g1_campaign_freeze(data_store:Any)->dict[str,Any]|None:
 ensure_g1_campaign_schema(data_store)
 with data_store._lock:
  row=data_store.conn.execute("SELECT payload FROM g1_campaign_freeze ORDER BY created_ts LIMIT 1").fetchone()
 return json.loads(row[0]) if row else None

def policy_from_freeze(payload:dict[str,Any])->G1CampaignPolicy:
 p=dict(payload.get("policy") or {})
 return G1CampaignPolicy(**{k:p[k] for k in G1CampaignPolicy.__dataclass_fields__ if k in p})
