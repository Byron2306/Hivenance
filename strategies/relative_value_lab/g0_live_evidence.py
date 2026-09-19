"""Build live G0 organ evidence only from already-observed Phoenix public data."""
from __future__ import annotations
import json
from typing import Any
from agents.horizon_context import HorizonContext
from .temporal_participation_bee import TemporalParticipationBee,ParticipationObservation

def _ret(closes:list[float],n:int)->float|None:
 if len(closes)<=n:return None
 a=float(closes[-n-1]);b=float(closes[-1])
 return ((b-a)/a)*10000.0 if a>0 else None

def horizon_from_feature(feature:Any)->HorizonContext|None:
 values=feature.values if isinstance(feature.values,dict) else {}
 ws=values.get("worker_series") if isinstance(values.get("worker_series"),dict) else {}
 closes=[float(x) for x in (ws.get("closes") or []) if x is not None]
 oracle=values.get("cex_market_oracle") if isinstance(values.get("cex_market_oracle"),dict) else {}
 hs=oracle.get("horizons") if isinstance(oracle.get("horizons"),dict) else {}
 r2=_ret(closes,2);r5=_ret(closes,5);r15=_ret(closes,15)
 r1h=(hs.get("1h") or {}).get("change_bps") if isinstance(hs.get("1h"),dict) else None
 r24=(hs.get("24h") or {}).get("change_bps") if isinstance(hs.get("24h"),dict) else None
 if r2 is None and r5 is None and r15 is None and r1h is None:return None
 signs=[1 if float(x)>1 else -1 if float(x)<-1 else 0 for x in (r2,r5,r15,r1h) if x is not None]
 nz=[x for x in signs if x]
 if nz and all(x>0 for x in nz):alignment="ALIGNED_UP"
 elif nz and all(x<0 for x in nz):alignment="ALIGNED_DOWN"
 elif not nz:alignment="NEUTRAL"
 else:alignment="CONFLICT"
 return HorizonContext(symbol=str(feature.symbol),timestamp=float(feature.timestamp_ms)/1000.0,
  micro={"return_10s_bps":None,"return_30s_bps":None,"score_bps":None,"bias":"UNKNOWN",
         "realized_vol_30s_bps":None},
  meso={"return_2m_bps":r2,"return_5m_bps":r5,
        "score_bps":None if r2 is None and r5 is None else sum(float(x or 0) for x in (r2,r5)),
        "bias":"UP" if (r5 or r2 or 0)>1 else "DOWN" if (r5 or r2 or 0)<-1 else "NEUTRAL"},
  macro={"return_15m_bps":r15,"return_1h_bps":r1h,"return_24h_bps":r24,
         "range_position_24h":None,
         "bias":"UP" if (r1h or r15 or 0)>1 else "DOWN" if (r1h or r15 or 0)<-1 else "NEUTRAL",
         "conviction":abs(sum(nz))/max(1,len(nz)) if nz else 0.0,
         "observed_15m_ready":r15 is not None,"observed_1h_ready":r1h is not None},
  alignment=alignment,regime_hint="TREND_UP" if alignment=="ALIGNED_UP" else "TREND_DOWN" if alignment=="ALIGNED_DOWN" else "MIXED",
  relative_strength={"30s":None,"2m":None,"5m":None,"15m":None,"1h":None},
  readiness={"micro":False,"meso":r2 is not None or r5 is not None,"macro_15m":r15 is not None,
             "macro_1h":r1h is not None,"macro_24h_ticker":r24 is not None})

def temporal_from_store(data_store:Any,feature:Any)->Any|None:
 values=feature.values if isinstance(feature.values,dict) else {}
 ws=values.get("worker_series") if isinstance(values.get("worker_series"),dict) else {}
 vols=ws.get("volumes") or []
 if not vols:return None
 current=float(vols[-1]);history=[]
 try:
  with data_store._lock:
   cur=data_store.conn.execute("SELECT ts,payload FROM observation_snapshots WHERE symbol=? AND ts<? ORDER BY ts DESC LIMIT 500",
    (str(feature.symbol),float(feature.timestamp_ms)/1000.0))
   rows=cur.fetchall()
 except Exception:return None
 for ts,raw in rows:
  try:p=json.loads(raw or "{}")
  except Exception:continue
  fv=((p.get("values") or {}).get("feature_vector") if isinstance(p.get("values"),dict) else None)
  if not isinstance(fv,dict):continue
  iv=fv.get("values") if isinstance(fv.get("values"),dict) else {}
  iws=iv.get("worker_series") if isinstance(iv.get("worker_series"),dict) else {}
  xs=iws.get("volumes") or []
  if xs:history.append(ParticipationObservation(int(float(ts)*1000),float(xs[-1]),None))
 if not history:return None
 return TemporalParticipationBee(min_same_hour_samples=5).observe(
  observed_at_ms=int(feature.timestamp_ms),volume=current,history=history,realized_move_bps=None)
