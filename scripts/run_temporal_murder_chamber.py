#!/usr/bin/env python3
"""Murder chamber for the frozen 1h-vs-24h conflict hypothesis.

Historical discovery only. No parameter optimization, execution, or promotion.
Tests incremental conflict value versus unconditional 1h reversion, costs,
non-overlap, per-symbol robustness, leave-one-symbol-out and episode clustering.
"""
from __future__ import annotations
import argparse,json,math,random,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
COSTS=(0,2,5,10,20)

def sg(x,d=1.):return 1 if x>d else -1 if x<-d else 0
def st(x):
 return {"n":len(x),"net_bps":round(sum(x),3),"mean_bps":round(statistics.fmean(x),3) if x else 0,
 "median_bps":round(statistics.median(x),3) if x else 0,"win_rate":round(sum(v>0 for v in x)/len(x),4) if x else 0}
def ci(x,n=1000):
 if len(x)<2:return [0,0]
 rng=random.Random(2306);means=[]
 for _ in range(n):means.append(statistics.fmean(rng.choice(x) for _ in x))
 means.sort();return [round(means[int(.025*n)],3),round(means[min(n-1,int(.975*n))],3)]
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/temporal_murder_chamber.json");a=p.parse_args()
 m=MarketMemory(a.database);events=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    p=float(r[i]["close"]);r1=(p/float(r[i-4]["close"])-1)*10000;r24=(p/float(r[i-96]["close"])-1)*10000
    d1,d24=sg(r1),sg(r24)
    if not d1:continue
    raw=(float(r[i+4]["close"])/p-1)*10000
    events.append({"symbol":s,"ts":int(r[i]["open_ts_ms"]),"r1":r1,"r24":r24,"d1":d1,"d24":d24,
      "conflict":bool(d24 and d1!=d24),"uncond":-d1*raw})
  conflict=[e for e in events if e["conflict"]]
  # non-overlap by symbol: at most one entry per 60 minutes
  non=[];last={}
  for e in sorted(conflict,key=lambda z:(z["ts"],z["symbol"])):
   if e["ts"]-last.get(e["symbol"],-10**18)>=3600000:non.append(e);last[e["symbol"]]=e["ts"]
  # market episodes: collapse same-hour correlated assets to one equal-weight episode
  eps={}
  for e in conflict:eps.setdefault(e["ts"]//3600000,[]).append(e["uncond"])
  episode=[statistics.fmean(v) for v in eps.values()]
  out={"schema":"hivenance_temporal_murder_chamber_v1","frozen_hypothesis":"fade 1h only when 1h direction conflicts with 24h direction; settle +1h",
   "coverage":{"events":len(events),"conflicts":len(conflict),"nonoverlap_conflicts":len(non),"market_episodes":len(episode)},
   "cost_sensitivity":{},"per_symbol":{},"leave_one_symbol_out":{},"controls":{},
   "note":"historical discovery only; bootstrap is descriptive and does not cure dependence or selection bias","execution_eligible":False,"promotion_eligible":False}
  for cost in COSTS:
   vals=[e["uncond"]-cost for e in conflict];q=st(vals);q["bootstrap_mean_95pct_bps"]=ci(vals);out["cost_sensitivity"][str(cost)]=q
  for s in SYMS:out["per_symbol"][s]=st([e["uncond"] for e in conflict if e["symbol"]==s])
  for s in SYMS:out["leave_one_symbol_out"][s]=st([e["uncond"] for e in conflict if e["symbol"]!=s])
  out["controls"]["conflict"]=st([e["uncond"] for e in conflict])
  out["controls"]["unconditional_revert_1h"]=st([e["uncond"] for e in events])
  out["controls"]["nonoverlap_conflict"]=st([e["uncond"] for e in non])
  out["controls"]["hourly_episode_equal_weight"]=st(episode)
  # incremental matched control: same timestamp/symbol universe, non-conflict unconditional fade
  out["controls"]["nonconflict_revert_1h"]=st([e["uncond"] for e in events if not e["conflict"]])
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== TEMPORAL MURDER CHAMBER =====")
  print("coverage",out["coverage"])
  for k,v in out["controls"].items():print(f"{k:30s} n={v['n']:5d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
  print("\nCOST SENSITIVITY")
  for k,v in out["cost_sensitivity"].items():print(f"cost={k:>2s}bps n={v['n']:5d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f} CI={v['bootstrap_mean_95pct_bps']}")
  print("\nPER SYMBOL")
  for k,v in out["per_symbol"].items():print(f"{k:10s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
  print(f"output: {a.output}\nHISTORICAL DISCOVERY ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
 return 0
if __name__=="__main__":raise SystemExit(main())
