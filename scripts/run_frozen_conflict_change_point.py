#!/usr/bin/env python3
"""Fine-grained change-point localization for the frozen conflict mechanism.

Descriptive historical diagnosis only. Finds where the observed outcome process
changes most sharply, then reports before/after windows and per-symbol timing.
A detected boundary is not a trading filter or prospective proof.
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
def stamp(ts):return datetime.fromtimestamp(ts/1000,tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/frozen_conflict_change_point.json");p.add_argument("--window",type=int,default=250);a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000;d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(r[i+4]["close"])/px-1)*10000
    ev.append({"s":s,"ts":int(r[i]["open_ts_ms"]),"v":-d1*raw})
  ev.sort(key=lambda e:(e["ts"],e["s"]))
  w=max(50,int(a.window));candidates=[]
  for i in range(w,len(ev)-w):
   left=[e["v"] for e in ev[i-w:i]];right=[e["v"] for e in ev[i:i+w]]
   gap=statistics.fmean(right)-statistics.fmean(left)
   candidates.append((abs(gap),gap,i,ev[i]["ts"]))
  candidates.sort(reverse=True)
  # keep separated candidates so one transition does not occupy all top slots
  top=[]
  for score,gap,i,ts in candidates:
   if all(abs(i-j)>=w//2 for _,_,j,_ in top):
    top.append((score,gap,i,ts))
   if len(top)>=8:break
  best=top[0];_,gap,idx,cp=best
  before=[e for e in ev if cp-24*3600000<=e["ts"]<cp];after=[e for e in ev if cp<=e["ts"]<cp+24*3600000]
  # 6-hour event-time windows around best point
  bins=defaultdict(list)
  for e in ev:
   rel=(e["ts"]-cp)//(6*3600000)
   if -8<=rel<=8:bins[int(rel)].append(e["v"])
  per_symbol={}
  for s in SYMS:
   rows=[e for e in ev if e["s"]==s]
   pre=[e["v"] for e in rows if cp-24*3600000<=e["ts"]<cp];post=[e["v"] for e in rows if cp<=e["ts"]<cp+24*3600000]
   per_symbol[s]={"pre24h":st(pre),"post24h":st(post),"delta_bps":round(statistics.fmean(post)-statistics.fmean(pre),3) if pre and post else None}
  out={"schema":"hivenance_frozen_conflict_change_point_v1","window_events":w,
   "best_boundary_utc":stamp(cp),"best_gap_bps":round(gap,3),"pre24h":st([e["v"] for e in before]),"post24h":st([e["v"] for e in after]),
   "top_boundaries":[{"utc":stamp(ts),"gap_bps":round(g,3),"index":i} for _,g,i,ts in top],
   "six_hour_windows":{str(k):{"start_utc":stamp(cp+k*6*3600000),**st(v)} for k,v in sorted(bins.items())},
   "per_symbol_24h":per_symbol,
   "warning":"post-outcome descriptive change-point localization; boundary is not causal, prospective, or a trading filter",
   "execution_eligible":False,"promotion_eligible":False}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== FROZEN CONFLICT CHANGE-POINT LOCALIZATION =====")
  print("best boundary",out["best_boundary_utc"],"gap",out["best_gap_bps"],"bps")
  print("pre24h",out["pre24h"]);print("post24h",out["post24h"])
  print("\nTOP SEPARATED BOUNDARIES")
  for x in out["top_boundaries"]:print(f"{x['utc']} gap={x['gap_bps']:+8.3f} bps")
  print("\n6H WINDOWS AROUND BEST")
  for k,x in out["six_hour_windows"].items():print(f"{int(k):+3d} {x['start_utc']} n={x['n']:3d} mean={x['mean_bps']:+8.3f} med={x['median_bps']:+8.3f} win={x['win_rate']:.3f}")
  print("\nPER SYMBOL +/-24H")
  for s,r in per_symbol.items():print(f"{s:9s} pre n={r['pre24h']['n']:3d} {r['pre24h']['mean_bps']:+8.3f} | post n={r['post24h']['n']:3d} {r['post24h']['mean_bps']:+8.3f} | delta={r['delta_bps']}")
  print(f"output: {a.output}\nHISTORICAL DIAGNOSIS ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
