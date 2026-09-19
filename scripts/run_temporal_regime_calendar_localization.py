#!/usr/bin/env python3
"""Locate the frozen conflict regime change in calendar time and test persistence.

No threshold/filter search. Uses the five already-defined chronological folds,
monthly/weekly reporting, rolling equal-count windows, and per-symbol era splits.
Historical diagnosis only.
"""
from __future__ import annotations
import argparse,json,statistics,sys
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def sg(x,d=1):return 1 if x>d else -1 if x<-d else 0
def st(v):
 return {"n":len(v),"mean_bps":round(statistics.fmean(v),3) if v else 0,"median_bps":round(statistics.median(v),3) if v else 0,
 "win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0}
def label(ts,fmt):return datetime.fromtimestamp(ts/1000,tz=timezone.utc).strftime(fmt)
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/temporal_regime_calendar_localization.json");p.add_argument("--rolling-events",type=int,default=200);a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000;d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(r[i+4]["close"])/px-1)*10000
    ev.append({"s":s,"ts":int(r[i]["open_ts_ms"]),"v":-d1*raw})
  ev.sort(key=lambda e:(e["ts"],e["s"]));times=sorted({e["ts"] for e in ev});bounds=[]
  for k in range(5):bounds.append((times[int(k*len(times)/5)],times[int((k+1)*len(times)/5)-1]))
  folds=[]
  for k,(lo,hi) in enumerate(bounds,1):
   rows=[e for e in ev if lo<=e["ts"]<=hi]
   folds.append({"fold":k,"start_utc":label(lo,"%Y-%m-%d %H:%M"),"end_utc":label(hi,"%Y-%m-%d %H:%M"),**st([e["v"] for e in rows])})
  monthly=defaultdict(list);weekly=defaultdict(list)
  for e in ev:
   monthly[label(e["ts"],"%Y-%m")].append(e["v"]);weekly[label(e["ts"],"%G-W%V")].append(e["v"])
  rolling=[];n=max(25,int(a.rolling_events))
  for i in range(0,len(ev),n):
   rows=ev[i:i+n]
   if not rows:continue
   rolling.append({"start_utc":label(rows[0]["ts"],"%Y-%m-%d"),"end_utc":label(rows[-1]["ts"],"%Y-%m-%d"),**st([e["v"] for e in rows])})
  split=bounds[2][0]
  per_symbol={}
  for s in SYMS:
   early=[e["v"] for e in ev if e["s"]==s and e["ts"]<split];late=[e["v"] for e in ev if e["s"]==s and e["ts"]>=split]
   per_symbol[s]={"pre_fold3":st(early),"fold3_onward":st(late),"delta_bps":round(statistics.fmean(late)-statistics.fmean(early),3) if early and late else None}
  out={"schema":"hivenance_temporal_regime_calendar_localization_v1","folds":folds,
   "fold3_boundary_utc":label(split,"%Y-%m-%d %H:%M"),"monthly":{k:st(v) for k,v in sorted(monthly.items())},
   "weekly":{k:st(v) for k,v in sorted(weekly.items())},"rolling_equal_event_windows":rolling,"per_symbol":per_symbol,
   "warning":"descriptive localization only; dates are not trading filters and do not establish causation","execution_eligible":False,"promotion_eligible":False}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== TEMPORAL REGIME CALENDAR LOCALIZATION =====")
  print("FOLDS")
  for f in folds:print(f"fold {f['fold']} {f['start_utc']} -> {f['end_utc']} n={f['n']:4d} mean={f['mean_bps']:+8.3f} med={f['median_bps']:+8.3f} win={f['win_rate']:.3f}")
  print("\nMONTHLY")
  for k,v in out["monthly"].items():print(f"{k:8s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
  print("\nROLLING EQUAL-EVENT WINDOWS")
  for x in rolling:print(f"{x['start_utc']} -> {x['end_utc']} n={x['n']:3d} mean={x['mean_bps']:+8.3f} med={x['median_bps']:+8.3f} win={x['win_rate']:.3f}")
  print("\nPER SYMBOL PRE-F3 -> F3+")
  for s,r in per_symbol.items():print(f"{s:9s} early n={r['pre_fold3']['n']:3d} {r['pre_fold3']['mean_bps']:+8.3f} | late n={r['fold3_onward']['n']:3d} {r['fold3_onward']['mean_bps']:+8.3f} | delta={r['delta_bps']:+8.3f}")
  print(f"\nfold3 boundary: {out['fold3_boundary_utc']} UTC")
  print(f"output: {a.output}\nHISTORICAL DIAGNOSIS ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
