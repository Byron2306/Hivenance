#!/usr/bin/env python3
"""Frozen world-state discrimination test.

Tests whether simple pre-event state variables explain the fold regime split
without turning post-hoc observations into a promoted trading rule.
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
 return {"n":len(v),"mean_bps":round(statistics.fmean(v),3) if v else 0,"median_bps":round(statistics.median(v),3) if v else 0,"win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0}
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/world_state_discrimination.json");a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000
    d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(r[i+4]["close"])/px-1)*10000
    pre=[(float(r[j]["close"])/float(r[j-1]["close"])-1)*10000 for j in range(i-15,i+1)]
    ev.append({"s":s,"ts":int(r[i]["open_ts_ms"]),"v":-d1*raw,"abs1":abs(r1),"abs24":abs(r24),"vol":statistics.pstdev(pre)})
  # thresholds are fixed descriptive round numbers suggested by the prior autopsy,
  # and are explicitly not promotion candidates.
  tests={
   "abs24_lt150":lambda e:e["abs24"]<150,
   "abs24_150_300":lambda e:150<=e["abs24"]<300,
   "abs24_300_plus":lambda e:e["abs24"]>=300,
   "pre4vol_lt25":lambda e:e["vol"]<25,
   "pre4vol_25_30":lambda e:25<=e["vol"]<30,
   "pre4vol_30_plus":lambda e:e["vol"]>=30,
  }
  out={"schema":"hivenance_world_state_discrimination_v1","descriptive_buckets":{},"joint_cells":{},"execution_eligible":False,
       "warning":"post-hoc descriptive discrimination only; no bucket is authorized as a trading filter"}
  for k,f in tests.items():out["descriptive_buckets"][k]=st([e["v"] for e in ev if f(e)])
  for ak,af in list(tests.items())[:3]:
   for vk,vf in list(tests.items())[3:]:
    out["joint_cells"][ak+"__"+vk]=st([e["v"] for e in ev if af(e) and vf(e)])
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== WORLD-STATE DISCRIMINATION =====")
  for k,v in out["descriptive_buckets"].items():print(f"{k:22s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
  print("\nJOINT CELLS")
  for k,v in out["joint_cells"].items():print(f"{k:42s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} win={v['win_rate']:.3f}")
  print(f"output: {a.output}\nPOST-HOC DESCRIPTION ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
