"""Immutable research-only target for prospective G1 organ-utility twins.

This is deliberately separate from the human-approved Phase-5 champion freeze.
It grants no deployment, transmission, execution, or promotion authority.
"""
from __future__ import annotations
import hashlib,json,time
from typing import Any
from strategies.volatility_breakout.shadow_flight import frozen_config_hash
from strategies.volatility_breakout.shadow_models import ShadowFreeze

AUTHORITY="SYNTHESIS_G1_RESEARCH_TARGET_ONLY"
MODEL_ID="breakout_continuation_v1"
ORDER_POLICY="market"

def _hash(x:Any)->str:
 return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def _conn(store:Any):
 return getattr(store,"conn",None) or getattr(store,"_conn",None)

def ensure_g1_research_target(store:Any,cfg:Any,*,created_ts:float|None=None)->dict[str,Any]:
 conn=_conn(store)
 if conn is None:raise RuntimeError("g1_research_target_store_unavailable")
 with getattr(store,"_lock",__import__("contextlib").nullcontext()):
  conn.execute("""CREATE TABLE IF NOT EXISTS g1_research_target_freeze(
   target_id TEXT PRIMARY KEY,created_ts REAL NOT NULL,payload_sha256 TEXT NOT NULL,payload TEXT NOT NULL)""")
  row=conn.execute("SELECT payload FROM g1_research_target_freeze ORDER BY created_ts ASC LIMIT 1").fetchone()
  if row:
   return json.loads(row[0])
  ts=float(time.time() if created_ts is None else created_ts)
  body={"schema":"hivenance_g1_research_target_v1","model_id":MODEL_ID,"order_policy":ORDER_POLICY,
   "symbol":None,"direction":None,"config_hash":frozen_config_hash(cfg),"authority":AUTHORITY,
   "execution_eligible":False,"promotion_eligible":False,"transmission_eligible":False}
  target_id="g1rt_"+_hash(body).split(":",1)[1][:24]
  payload={**body,"target_id":target_id,"created_ts":ts}
  encoded=json.dumps(payload,sort_keys=True,separators=(",",":"))
  conn.execute("INSERT INTO g1_research_target_freeze VALUES(?,?,?,?)",
   (target_id,ts,_hash(payload),encoded))
  conn.commit()
  return payload

def get_g1_research_target(store:Any)->dict[str,Any]|None:
 conn=_conn(store)
 if conn is None:return None
 try:
  with getattr(store,"_lock",__import__("contextlib").nullcontext()):
   row=conn.execute("SELECT payload FROM g1_research_target_freeze ORDER BY created_ts ASC LIMIT 1").fetchone()
  return json.loads(row[0]) if row else None
 except Exception:
  return None

def shadow_freeze_from_research_target(target:dict[str,Any])->ShadowFreeze:
 if target.get("authority")!=AUTHORITY:raise ValueError("g1_research_target_authority_invalid")
 if target.get("execution_eligible") is not False or target.get("promotion_eligible") is not False:
  raise ValueError("g1_research_target_must_be_non_authoritative")
 return ShadowFreeze(
  freeze_id=str(target["target_id"]),phase4_run_id="G1_RESEARCH_ONLY",
  candidate_key="G1_RESEARCH_TARGET:"+str(target["model_id"]),model_id=str(target["model_id"]),
  order_policy=str(target["order_policy"]),approved_by="G1_RESEARCH_PROTOCOL",
  approved_ts=float(target["created_ts"]),phase4_dataset_hash="RESEARCH_ONLY_NO_PHASE4_AUTHORITY",
  config_hash=str(target["config_hash"]),symbol=None,direction=None,status="ACTIVE",
  shadow_only=True,execution_eligible=False)


PRIMARY_MODEL_IDS=("breakout_continuation_v1","exhaustion_mean_reversion_v1")

def get_latest_g1_research_target(store:Any)->dict[str,Any]|None:
 conn=_conn(store)
 if conn is None:return None
 try:
  with getattr(store,"_lock",__import__("contextlib").nullcontext()):
   row=conn.execute("SELECT payload FROM g1_research_target_freeze ORDER BY created_ts DESC LIMIT 1").fetchone()
  return json.loads(row[0]) if row else None
 except Exception:
  return None

def freeze_g1_research_target_successor(store:Any,cfg:Any,*,campaign_id:str|None=None,
 model_ids:tuple[str,...]=PRIMARY_MODEL_IDS,order_policy:str=ORDER_POLICY,
 predecessor_target_id:str|None=None,created_ts:float|None=None)->dict[str,Any]:
 conn=_conn(store)
 if conn is None:raise RuntimeError("g1_research_target_store_unavailable")
 mids=tuple(dict.fromkeys(str(x) for x in model_ids if str(x)))
 if not mids:raise ValueError("g1_research_target_models_required")
 ts=float(time.time() if created_ts is None else created_ts)
 body={"schema":"hivenance_g1_research_target_v2","campaign_id":(str(campaign_id) if campaign_id else None),
  "model_ids":mids,"order_policy":str(order_policy),"symbol":None,"direction":None,
  "predecessor_target_id":predecessor_target_id,"config_hash":frozen_config_hash(cfg),
  "authority":AUTHORITY,"execution_eligible":False,"promotion_eligible":False,
  "transmission_eligible":False}
 target_id="g1rt_"+_hash(body).split(":",1)[1][:24]
 payload={**body,"target_id":target_id,"created_ts":ts}
 encoded=json.dumps(payload,sort_keys=True,separators=(",",":"))
 with getattr(store,"_lock",__import__("contextlib").nullcontext()):
  conn.execute("""CREATE TABLE IF NOT EXISTS g1_research_target_freeze(
   target_id TEXT PRIMARY KEY,created_ts REAL NOT NULL,payload_sha256 TEXT NOT NULL,payload TEXT NOT NULL)""")
  row=conn.execute("SELECT payload FROM g1_research_target_freeze WHERE target_id=?",(target_id,)).fetchone()
  if row:return {"created":False,**json.loads(row[0])}
  conn.execute("INSERT INTO g1_research_target_freeze VALUES(?,?,?,?)",
   (target_id,ts,_hash(payload),encoded));conn.commit()
 return {"created":True,**payload}

def shadow_freezes_from_research_target(target:dict[str,Any])->tuple[ShadowFreeze,...]:
 if target.get("authority")!=AUTHORITY:raise ValueError("g1_research_target_authority_invalid")
 if target.get("execution_eligible") is not False or target.get("promotion_eligible") is not False:
  raise ValueError("g1_research_target_must_be_non_authoritative")
 mids=tuple(target.get("model_ids") or ())
 if not mids and target.get("model_id"):mids=(str(target["model_id"]),)
 out=[]
 for model_id in mids:
  freeze_id=str(target["target_id"])+":"+_hash({"model_id":model_id})[-12:]
  out.append(ShadowFreeze(
   freeze_id=freeze_id,phase4_run_id="G1_RESEARCH_ONLY",
   candidate_key="G1_RESEARCH_TARGET:"+str(model_id),model_id=str(model_id),
   order_policy=str(target["order_policy"]),approved_by="G1_RESEARCH_PROTOCOL",
   approved_ts=float(target["created_ts"]),phase4_dataset_hash="RESEARCH_ONLY_NO_PHASE4_AUTHORITY",
   config_hash=str(target["config_hash"]),symbol=None,direction=None,status="ACTIVE",
   shadow_only=True,execution_eligible=False))
 return tuple(out)
