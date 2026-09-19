#!/usr/bin/env python3
"""Blind organ exam for existing Horizon semantics against frozen conflict events.

The organ sees only pre-outcome market state. We do not tune a new threshold.
Historical diagnostic only.
"""
from __future__ import annotations
import argparse,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
from agents.world_state import WorldStateBuilder
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def sg(x,d=1):return 1 if x>d else -1 if x<-d else 0
def st(v):
 return {"n":len(v),"mean_bps":round(statistics.fmean(v),3) if v else 0,"median_bps":round(statistics.median(v),3) if v else 0,"win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0}
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/horizon_blind_organ_exam.json");a=p.parse_args()
 m=MarketMemory(a.database);b=WorldStateBuilder(m);groups={};n=0
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000
    d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    ts=int(r[i]["open_ts_ms"]);raw=(float(r[i+4]["close"])/px-1)*10000;v=-d1*raw
    try:page=b.build(s,ts,SYMS)
    except Exception:continue
    h=page.horizon
    labels={
      "alignment":h.get("alignment","UNKNOWN"),
      "regime_hint":h.get("regime_hint","UNKNOWN"),
      "macro_direction":str((h.get("macro") or {}).get("direction","UNKNOWN")),
      "meso_direction":str((h.get("meso") or {}).get("direction","UNKNOWN")),
    }
    for dim,label in labels.items():groups.setdefault(dim,{}).setdefault(label,[]).append(v)
    n+=1
  out={"schema":"hivenance_horizon_blind_organ_exam_v1","events":n,
    "groups":{d:{k:st(v) for k,v in g.items()} for d,g in groups.items()},
    "question":"Do existing Horizon semantics, without outcome tuning, partition the frozen conflict mechanism into economically different states?",
    "execution_eligible":False,"promotion_eligible":False}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== HORIZON BLIND ORGAN EXAM =====")
  print("events",n)
  for d,g in out["groups"].items():
   print("\n--",d,"--")
   for k,v in sorted(g.items(),key=lambda kv:kv[1]["n"],reverse=True):
    print(f"{k:24s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
  print(f"output: {a.output}\nHISTORICAL ORGAN DIAGNOSTIC ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
