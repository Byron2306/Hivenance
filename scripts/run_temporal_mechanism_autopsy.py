#!/usr/bin/env python3
"""Episode-aware temporal mechanism autopsy.

Freezes the discovered conflict rule and asks where its incremental value lives:
magnitude, direction, hour, symbol, breadth and market episode. Historical only.
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
 "win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0,"net_bps":round(sum(v),3)}
def mag(v):
 a=abs(v)
 return "0_10" if a<10 else "10_25" if a<25 else "25_50" if a<50 else "50_100" if a<100 else "100_PLUS"
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/temporal_mechanism_autopsy.json");a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000
    d1,d24=sg(r1),sg(r24)
    if not d1:continue
    raw=(float(r[i+4]["close"])/px-1)*10000;value=-d1*raw
    ev.append({"s":s,"ts":int(r[i]["open_ts_ms"]),"r1":r1,"r24":r24,"d1":d1,"d24":d24,"conflict":bool(d24 and d1!=d24),"v":value})
  groups={}
  def add(dim,key,val):groups.setdefault(dim,{}).setdefault(str(key),[]).append(val)
  for e in ev:
   if not e["conflict"]:continue
   add("one_hour_magnitude",mag(e["r1"]),e["v"]);add("one_hour_direction","UP" if e["d1"]>0 else "DOWN",e["v"])
   add("day_direction","UP" if e["d24"]>0 else "DOWN",e["v"])
   add("utc_hour",(e["ts"]//3600000)%24,e["v"])
  # episode breadth: how many symbols conflict in same hour, and equal-weight episode value
  eps={}
  for e in ev:
   if e["conflict"]:eps.setdefault(e["ts"]//3600000,[]).append(e)
  episode_rows=[]
  for h,rows in eps.items():
   vals=[x["v"] for x in rows];breadth=len({x["s"] for x in rows})
   episode_rows.append({"hour":h,"breadth":breadth,"mean_bps":statistics.fmean(vals),"n":len(vals)})
   add("episode_breadth",breadth,statistics.fmean(vals))
  # incremental conflict vs nonconflict by symbol
  incremental={}
  for s in SYMS:
   yes=[e["v"] for e in ev if e["s"]==s and e["conflict"]];no=[e["v"] for e in ev if e["s"]==s and not e["conflict"]]
   incremental[s]={"conflict":st(yes),"nonconflict":st(no),
     "incremental_mean_bps":round((statistics.fmean(yes) if yes else 0)-(statistics.fmean(no) if no else 0),3)}
  out={"schema":"hivenance_temporal_mechanism_autopsy_v1","groups":{d:{k:st(v) for k,v in g.items()} for d,g in groups.items()},
   "incremental_by_symbol":incremental,"episodes":episode_rows,
   "note":"historical mechanism discovery only; no threshold selection should be promoted from this file","execution_eligible":False}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== TEMPORAL MECHANISM AUTOPSY =====")
  for d in ("one_hour_magnitude","one_hour_direction","day_direction","episode_breadth"):
   print("\n--",d,"--")
   for k,v in out["groups"].get(d,{}).items():print(f"{k:12s} n={v['n']:5d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
  print("\n-- INCREMENTAL CONFLICT VALUE BY SYMBOL --")
  for s,v in incremental.items():print(f"{s:10s} conflict={v['conflict']['mean_bps']:+8.3f} nonconflict={v['nonconflict']['mean_bps']:+8.3f} incremental={v['incremental_mean_bps']:+8.3f}")
  print(f"output: {a.output}\nHISTORICAL DISCOVERY ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
