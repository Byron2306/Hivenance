#!/usr/bin/env python3
"""Regime-change autopsy for the frozen temporal conflict mechanism.

Explains why early chronological folds fail and later folds work without tuning
a new trading rule. Historical research only.
"""
from __future__ import annotations
import argparse,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def sg(x,d=1):return 1 if x>d else -1 if x<-d else 0
def st(v):
 return {"n":len(v),"mean_bps":round(statistics.fmean(v),3) if v else 0,"median_bps":round(statistics.median(v),3) if v else 0,
 "win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0}
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/temporal_regime_change_autopsy.json");a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000
    d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(r[i+4]["close"])/px-1)*10000
    # pre-event 4h and 6h realized movement proxies, known at decision time
    pre4=[(float(r[j]["close"])/float(r[j-1]["close"])-1)*10000 for j in range(i-15,i+1)]
    pre6=[(float(r[j]["close"])/float(r[j-1]["close"])-1)*10000 for j in range(i-23,i+1)]
    ev.append({"s":s,"ts":int(r[i]["open_ts_ms"]),"v":-d1*raw,"r1":r1,"r24":r24,
      "abs1":abs(r1),"abs24":abs(r24),"pre4_vol":statistics.pstdev(pre4),"pre6_vol":statistics.pstdev(pre6)})
  times=sorted({e["ts"] for e in ev})
  for e in ev:e["fold"]=min(5,1+int(5*times.index(e["ts"])/len(times)))
  folds={}
  for k in range(1,6):
   x=[e for e in ev if e["fold"]==k];vals=[e["v"] for e in x]
   folds[str(k)]={**st(vals),"start_ts":min(e["ts"] for e in x),"end_ts":max(e["ts"] for e in x),
    "mean_abs_1h_bps":round(statistics.fmean(e["abs1"] for e in x),3),
    "mean_abs_24h_bps":round(statistics.fmean(e["abs24"] for e in x),3),
    "mean_pre4_vol_bps":round(statistics.fmean(e["pre4_vol"] for e in x),3),
    "mean_pre6_vol_bps":round(statistics.fmean(e["pre6_vol"] for e in x),3)}
  # Rolling hourly episodes, descriptive only.
  eps={}
  for e in ev:eps.setdefault(e["ts"]//3600000,[]).append(e)
  rolling=[]
  keys=sorted(eps)
  for z in range(len(keys)):
   lo=max(0,z-23);batch=[x for k in keys[lo:z+1] for x in eps[k]]
   rolling.append({"hour":keys[z],"episodes":z-lo+1,"mean_bps":round(statistics.fmean(x["v"] for x in batch),3),
    "win_rate":round(sum(x["v"]>0 for x in batch)/len(batch),4),"n":len(batch)})
  out={"schema":"hivenance_temporal_regime_change_autopsy_v1","folds":folds,"rolling_24_episode_hours":rolling,
   "note":"descriptive regime autopsy only; variables must not be promoted as filters without a new frozen test","execution_eligible":False}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== TEMPORAL REGIME-CHANGE AUTOPSY =====")
  for k,v in folds.items():print(f"fold {k} n={v['n']:4d} mean={v['mean_bps']:+8.3f} win={v['win_rate']:.3f} | abs1h={v['mean_abs_1h_bps']:.1f} abs24h={v['mean_abs_24h_bps']:.1f} pre4vol={v['mean_pre4_vol_bps']:.1f}")
  print(f"output: {a.output}\nDESCRIPTIVE ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
