#!/usr/bin/env python3
"""Path-geometry autopsy for the frozen 1h-vs-24h conflict mechanism.

Asks whether the early/late regime switch survives after conditioning on the
shape of the pre-event path. All features use bars at or before T. Historical
diagnosis only. No threshold search or promotion.
"""
from __future__ import annotations
import argparse,json,math,statistics,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def sg(x,d=1):return 1 if x>d else -1 if x<-d else 0
def st(v):
 return {"n":len(v),"mean_bps":round(statistics.fmean(v),3) if v else 0,"median_bps":round(statistics.median(v),3) if v else 0,
 "win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0}
def quantile_bins(values,n=4):
 xs=sorted(values)
 cuts=[]
 for k in range(1,n):
  cuts.append(xs[min(len(xs)-1,int(k*len(xs)/n))])
 return cuts
def bucket(x,cuts):
 return sum(x>c for c in cuts)
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/path_geometry_regime_autopsy.json");a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000;d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(r[i+4]["close"])/px-1)*10000
    # pre-event path, all ending at T
    closes=[float(r[j]["close"]) for j in range(i-16,i+1)]
    rets=[(closes[j]/closes[j-1]-1)*10000 for j in range(1,len(closes))]
    path=sum(abs(x) for x in rets);net=abs((closes[-1]/closes[0]-1)*10000)
    efficiency=net/path if path>0 else 0
    signed=[sg(x,0.0) for x in rets if x]
    flips=sum(1 for j in range(1,len(signed)) if signed[j]!=signed[j-1])
    flip_rate=flips/max(1,len(signed)-1)
    hi=max(float(r[j]["high"]) for j in range(i-16,i+1));lo=min(float(r[j]["low"]) for j in range(i-16,i+1))
    range_bps=(hi/lo-1)*10000 if lo>0 else 0
    pos=(px-lo)/max(hi-lo,1e-12)
    last4=[(float(r[j]["close"])/float(r[j-1]["close"])-1)*10000 for j in range(i-3,i+1)]
    accel=abs(last4[-1])-statistics.fmean(abs(x) for x in last4[:-1]) if len(last4)>=4 else 0
    ev.append({"s":s,"ts":int(r[i]["open_ts_ms"]),"v":-d1*raw,"eff":efficiency,"flip":flip_rate,"range":range_bps,"pos":pos,"accel":accel})
  times=sorted({e["ts"] for e in ev});bounds=[]
  for k in range(5):bounds.append((times[int(k*len(times)/5)],times[int((k+1)*len(times)/5)-1]))
  for e in ev:
   e["fold"]=next(k+1 for k,(lo,hi) in enumerate(bounds) if lo<=e["ts"]<=hi);e["era"]="EARLY" if e["fold"]<=2 else "LATE"
  features=["eff","flip","range","pos","accel"]
  cuts={f:quantile_bins([e[f] for e in ev],4) for f in features}
  out={"schema":"hivenance_path_geometry_regime_autopsy_v1","feature_cuts":cuts,"by_feature_quartile":{},"early_vs_late_within_quartile":{},
       "warning":"historical diagnosis only; quartiles are descriptive pooled partitions, not promoted filters","execution_eligible":False,"promotion_eligible":False}
  for f in features:
   out["by_feature_quartile"][f]={};out["early_vs_late_within_quartile"][f]={}
   for q in range(4):
    rows=[e for e in ev if bucket(e[f],cuts[f])==q]
    early=[e["v"] for e in rows if e["era"]=="EARLY"];late=[e["v"] for e in rows if e["era"]=="LATE"]
    out["by_feature_quartile"][f][str(q+1)]=st([e["v"] for e in rows])
    out["early_vs_late_within_quartile"][f][str(q+1)]={"early":st(early),"late":st(late),
      "delta_bps":round(statistics.fmean(late)-statistics.fmean(early),3) if early and late else None}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== PATH GEOMETRY REGIME AUTOPSY =====")
  for f in features:
   print("\n",f.upper(),"cuts",cuts[f])
   for q,r in out["early_vs_late_within_quartile"][f].items():
    print(f"Q{q} early n={r['early']['n']:3d} {r['early']['mean_bps']:+8.3f} | late n={r['late']['n']:3d} {r['late']['mean_bps']:+8.3f} | delta={r['delta_bps']:+8.3f}")
  print(f"output: {a.output}\nHISTORICAL DIAGNOSIS ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
