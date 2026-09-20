"""Build live G0 organ evidence only from already-observed Phoenix public data."""
from __future__ import annotations
import json
from typing import Any
from agents.horizon_context import HorizonContext
from .temporal_participation_bee import TemporalParticipationBee,ParticipationObservation
from .comparison_engine import ComparisonEngine,ComparisonReference

def _ret(closes:list[float],n:int)->float|None:
 if len(closes)<=n:return None
 a=float(closes[-n-1]);b=float(closes[-1])
 return ((b-a)/a)*10000.0 if a>0 else None

def horizon_from_feature(feature:Any)->HorizonContext|None:
 values=feature.values if isinstance(feature.values,dict) else {}
 lattice=values.get("full_temporal_lattice") if isinstance(values.get("full_temporal_lattice"),dict) else {}
 if lattice:
  micro_rows=lattice.get("micro") if isinstance(lattice.get("micro"),dict) else {}
  meso_rows=lattice.get("meso") if isinstance(lattice.get("meso"),dict) else {}
  macro_rows=lattice.get("macro") if isinstance(lattice.get("macro"),dict) else {}
  oracle_rows=lattice.get("oracle") if isinstance(lattice.get("oracle"),dict) else {}
  conflict=lattice.get("conflict") if isinstance(lattice.get("conflict"),dict) else {}
  def v(rows,key):
   row=rows.get(key) if isinstance(rows.get(key),dict) else {}
   return row.get("change_bps") if row.get("status")=="PRESENT" else None
  r10=v(micro_rows,"10s");r30=v(micro_rows,"30s");r2=v(micro_rows,"2m");r5=v(micro_rows,"5m")
  r15=v(meso_rows,"15m");r1h=v(meso_rows,"1h");r4h=v(meso_rows,"4h");r24=v(meso_rows,"24h")
  r7d=v(macro_rows,"7d");r30d=v(macro_rows,"30d");r365d=v(macro_rows,"365d")
  o1h=v(oracle_rows,"1h");o5h=v(oracle_rows,"5h");o24=v(oracle_rows,"24h");o7d=v(oracle_rows,"7d");o30d=v(oracle_rows,"30d")
  signs=[1 if float(x)>1 else -1 if float(x)<-1 else 0 for x in (r2,r5,r15,r1h,r4h,r24,r7d,r30d,r365d) if x is not None]
  nz=[x for x in signs if x]
  if nz and all(x>0 for x in nz):alignment="ALIGNED_UP"
  elif nz and all(x<0 for x in nz):alignment="ALIGNED_DOWN"
  elif not nz:alignment="NEUTRAL"
  else:alignment="CONFLICT"
  return HorizonContext(symbol=str(feature.symbol),timestamp=float(feature.timestamp_ms)/1000.0,
   micro={"return_10s_bps":r10,"return_30s_bps":r30,
          "score_bps":None if r10 is None and r30 is None else sum(float(x or 0) for x in (r10,r30)),
          "bias":str(conflict.get("micro_bias") or "NEUTRAL_OR_MISSING"),
          "realized_vol_30s_bps":None},
   meso={"return_2m_bps":r2,"return_5m_bps":r5,
         "score_bps":None if r2 is None and r5 is None else sum(float(x or 0) for x in (r2,r5)),
         "bias":str(conflict.get("meso_bias") or "NEUTRAL_OR_MISSING"),
         "return_15m_bps":r15,"return_1h_bps":r1h,"return_4h_bps":r4h,"return_24h_bps":r24},
   macro={"return_15m_bps":r15,"return_1h_bps":r1h,"return_4h_bps":r4h,"return_24h_bps":r24,
          "return_7d_bps":r7d,"return_30d_bps":r30d,"return_365d_bps":r365d,
          "oracle_1h_bps":o1h,"oracle_5h_bps":o5h,"oracle_24h_bps":o24,
          "oracle_7d_bps":o7d,"oracle_30d_bps":o30d,
          "range_position_24h":None,"bias":str(conflict.get("macro_bias") or "NEUTRAL_OR_MISSING"),
          "conviction":abs(sum(nz))/max(1,len(nz)) if nz else 0.0,
          "observed_15m_ready":r15 is not None,"observed_1h_ready":r1h is not None,
          "temporal_conflict":dict(conflict),
          "temporal_lattice_id":lattice.get("lattice_id")},
   alignment=alignment,
   regime_hint="TREND_UP" if alignment=="ALIGNED_UP" else "TREND_DOWN" if alignment=="ALIGNED_DOWN" else "MIXED",
   relative_strength={"30s":None,"2m":None,"5m":None,"15m":None,"1h":None},
   readiness={"micro":r10 is not None or r30 is not None,"meso":any(x is not None for x in (r2,r5,r15,r1h,r4h,r24)),
              "macro_15m":r15 is not None,"macro_1h":r1h is not None,"macro_24h_ticker":r24 is not None,
              "macro_7d":r7d is not None,"macro_30d":r30d is not None,"macro_365d":r365d is not None,
              "oracle_1h":o1h is not None,"oracle_5h":o5h is not None,"oracle_24h":o24 is not None,
              "oracle_7d":o7d is not None,"oracle_30d":o30d is not None})
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

def _worker_realized_move_bps(worker_series:dict[str,Any],short_window:int=5)->float|None:
 closes=worker_series.get("closes") or []
 try:
  xs=[float(x) for x in closes if x is not None]
 except Exception:
  return None
 window=max(1,int(short_window))
 if len(xs)<=window:
  return None
 start=xs[-(window+1)]
 end=xs[-1]
 if start<=0:
  return None
 return ((end-start)/start)*10000.0


def temporal_from_store(data_store:Any,feature:Any)->Any|None:
 values=feature.values if isinstance(feature.values,dict) else {}
 ws=values.get("worker_series") if isinstance(values.get("worker_series"),dict) else {}
 vols=ws.get("volumes") or []
 if not vols:return None

 current=float(vols[-1])
 current_move=_worker_realized_move_bps(ws,5)
 history=[]

 try:
  with data_store._lock:
   cur=data_store.conn.execute(
    "SELECT ts,payload FROM observation_snapshots WHERE symbol=? AND ts<? ORDER BY ts DESC LIMIT 500",
    (str(feature.symbol),float(feature.timestamp_ms)/1000.0)
   )
   rows=cur.fetchall()
 except Exception:
  return None

 for ts,raw in rows:
  try:
   p=json.loads(raw or "{}")
  except Exception:
   continue

  fv=((p.get("values") or {}).get("feature_vector")
      if isinstance(p.get("values"),dict) else None)
  if not isinstance(fv,dict):
   continue

  iv=fv.get("values") if isinstance(fv.get("values"),dict) else {}
  iws=iv.get("worker_series") if isinstance(iv.get("worker_series"),dict) else {}
  volumes=iws.get("volumes") or []
  if not volumes:
   continue

  historical_move=_worker_realized_move_bps(iws,5)

  history.append(
   ParticipationObservation(
    int(float(ts)*1000),
    float(volumes[-1]),
    historical_move,
   )
  )

 if not history:
  return None

 return TemporalParticipationBee(min_same_hour_samples=5).observe(
  observed_at_ms=int(feature.timestamp_ms),
  volume=current,
  history=history,
  realized_move_bps=current_move,
 )


def latest_shadow_learning(data_store:Any)->tuple[dict[str,Any],...]:
 try:
  rows=data_store.get_phase5_adversarial_shadow_receipts(limit=50)
 except Exception:
  return ()
 out=[]
 for row in rows:
  try:
   p=json.loads(row.get("payload") or "{}") if isinstance(row.get("payload"),str) else dict(row.get("payload") or {})
  except Exception:
   continue
  learning=p.get("learning") if isinstance(p.get("learning"),dict) else None
  if not learning or learning.get("authority")!="PROSPECTIVE_SHADOW_RESEARCH_ONLY":continue
  q=dict(learning);digest=str(row.get("payload_sha256") or "")
  if digest:q["source_artifacts"]=[{"sha256":digest}]
  out.append(q)
 return tuple(out)

def same_hour_comparison(data_store:Any,feature:Any)->Any|None:
 current_values={"volume_zscore":feature.volume_zscore,"volatility_expansion":feature.volatility_expansion,
  "spread_bps":feature.spread_bps,"book_imbalance":feature.book_imbalance}
 refs=[]
 try:
  with data_store._lock:
   cur=data_store.conn.execute("SELECT ts,payload FROM observation_snapshots WHERE symbol=? AND ts<? ORDER BY ts DESC LIMIT 500",
    (str(feature.symbol),float(feature.timestamp_ms)/1000.0));rows=cur.fetchall()
 except Exception:return None
 from datetime import datetime,timezone
 for i,(ts,raw) in enumerate(rows):
  try:p=json.loads(raw or "{}")
  except Exception:continue
  fv=((p.get("values") or {}).get("feature_vector") if isinstance(p.get("values"),dict) else None)
  if not isinstance(fv,dict):continue
  root="sha256:"+__import__("hashlib").sha256((raw or "").encode()).hexdigest()
  refs.append(ComparisonReference(f"obs:{i}",int(float(ts)*1000),str(feature.symbol),
   datetime.fromtimestamp(float(ts),tz=timezone.utc).hour,
   {"volume_zscore":fv.get("volume_zscore"),"volatility_expansion":fv.get("volatility_expansion"),
    "spread_bps":fv.get("spread_bps"),"book_imbalance":fv.get("book_imbalance")},(root,)))
 if not refs:return None
 hour=datetime.fromtimestamp(float(feature.timestamp_ms)/1000.0,tz=timezone.utc).hour
 return ComparisonEngine().same_utc_hour_baseline(observed_at_ms=int(feature.timestamp_ms),
  symbol=str(feature.symbol),utc_hour=hour,current_features=current_values,references=refs,
  feature_names=("volume_zscore","volatility_expansion","spread_bps","book_imbalance"))
