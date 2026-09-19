"""Settle mature canonical G0 twins from one shared Phoenix public tape."""
from __future__ import annotations
from types import SimpleNamespace
from typing import Any
from .g0_shadow_twins import G0ShadowTwin,settle_shadow_twin
from .g0_twin_store import mature_frozen_twins,persist_twin_settlement

def settle_mature_g0_twins(data_store:Any,settler:Any,*,now_ts:float,tolerance_sec:int=900)->dict[str,int]:
 out={"examined":0,"settled":0,"errors":0}
 for p in mature_frozen_twins(data_store,now_ts=now_ts):
  out["examined"]+=1
  try:
   fi=p["full_intent"];bi=p["ablated_intent"]
   if str(fi.get("symbol"))!=str(bi.get("symbol")):raise ValueError("twin_symbol_mismatch")
   start=min(float(fi.get("created_ts") or 0),float(bi.get("created_ts") or 0));target=float(p["target_ts"])
   with data_store._lock:
    c=data_store.conn.cursor();rows=c.execute("""SELECT * FROM observation_snapshots
     WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts ASC""",
     (fi.get("symbol"),start,target+float(tolerance_sec))).fetchall();cols=[x[0] for x in c.description]
   obs=[]
   import json
   for raw in rows:
    x=dict(zip(cols,raw))
    try:
     q=json.loads(x.get("payload") or "{}")
     if isinstance(q,dict):x.update(q)
    except Exception:pass
    obs.append(x)
   twin=G0ShadowTwin(p["organ_id"],p["opportunity_id"],p["world_state_hash"],fi,bi)
   s=settle_shadow_twin(twin=twin,settler=settler,observations=obs,settled_ts=now_ts)
   if persist_twin_settlement(data_store,twin_freeze_id=p["twin_freeze_id"],payload=s.to_dict(),settled_ts=now_ts):out["settled"]+=1
  except Exception:out["errors"]+=1
 return out
