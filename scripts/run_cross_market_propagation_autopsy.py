#!/usr/bin/env python3
"""Cross-market propagation autopsy for the frozen conflict regime shift.

Tests whether early/late behavior differs with simultaneous market breadth,
conflict breadth, peer direction, and BTC/ETH leadership. Uses only same-or-prior
15m bars at T. Historical diagnosis only, no threshold optimization/promotion.
"""
from __future__ import annotations
import argparse,json,statistics,sys
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
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/cross_market_propagation_autopsy.json");a=p.parse_args()
 m=MarketMemory(a.database)
 try:
  bars={s:m.bars(s,"15m",limit=100000) for s in SYMS}
  idx={s:{int(r["open_ts_ms"]):i for i,r in enumerate(rows)} for s,rows in bars.items()}
  ev=[]
  for s,rows in bars.items():
   for i in range(96,len(rows)-4):
    ts=int(rows[i]["open_ts_ms"]);px=float(rows[i]["close"]);r1=(px/float(rows[i-4]["close"])-1)*10000;r24=(px/float(rows[i-96]["close"])-1)*10000;d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(rows[i+4]["close"])/px-1)*10000
    peers=[];conflicts=0;up1=0;up24=0
    for ps,prows in bars.items():
     j=idx[ps].get(ts)
     if j is None or j<96:continue
     ppx=float(prows[j]["close"]);pr1=(ppx/float(prows[j-4]["close"])-1)*10000;pr24=(ppx/float(prows[j-96]["close"])-1)*10000;pd1,pd24=sg(pr1),sg(pr24)
     if pd1:up1+=pd1
     if pd24:up24+=pd24
     if pd1 and pd24 and pd1!=pd24:conflicts+=1
     if ps!=s:peers.append((ps,pr1,pr24,pd1,pd24))
    peer1=statistics.median([x[1] for x in peers]) if peers else 0
    peer24=statistics.median([x[2] for x in peers]) if peers else 0
    btc=next((x for x in peers if x[0]=="BTC/USD"),None) if s!="BTC/USD" else None
    eth=next((x for x in peers if x[0]=="ETH/USD"),None) if s!="ETH/USD" else None
    leaders=[x for x in (btc,eth) if x]
    leader1=statistics.median([x[1] for x in leaders]) if leaders else peer1
    leader24=statistics.median([x[2] for x in leaders]) if leaders else peer24
    ev.append({"s":s,"ts":ts,"v":-d1*raw,"d1":d1,"d24":d24,"conflicts":conflicts,"breadth1":up1,"breadth24":up24,
      "peer1":peer1,"peer24":peer24,"leader1":leader1,"leader24":leader24,
      "peer1_agrees_local":sg(peer1)==d1,"peer24_agrees_macro":sg(peer24)==d24,
      "leader1_agrees_local":sg(leader1)==d1,"leader24_agrees_macro":sg(leader24)==d24})
  times=sorted({e["ts"] for e in ev});bounds=[]
  for k in range(5):bounds.append((times[int(k*len(times)/5)],times[int((k+1)*len(times)/5)-1]))
  for e in ev:
   e["fold"]=next(k+1 for k,(lo,hi) in enumerate(bounds) if lo<=e["ts"]<=hi);e["era"]="EARLY" if e["fold"]<=2 else "LATE"
  tests={
   "conflict_breadth_1_2":lambda e:e["conflicts"]<=2,
   "conflict_breadth_3_5":lambda e:3<=e["conflicts"]<=5,
   "conflict_breadth_6_8":lambda e:e["conflicts"]>=6,
   "peer1_agrees_local":lambda e:e["peer1_agrees_local"],
   "peer1_opposes_local":lambda e:not e["peer1_agrees_local"],
   "peer24_agrees_macro":lambda e:e["peer24_agrees_macro"],
   "peer24_opposes_macro":lambda e:not e["peer24_agrees_macro"],
   "leaders1_agree_local":lambda e:e["leader1_agrees_local"],
   "leaders1_oppose_local":lambda e:not e["leader1_agrees_local"],
   "leaders24_agree_macro":lambda e:e["leader24_agrees_macro"],
   "leaders24_oppose_macro":lambda e:not e["leader24_agrees_macro"],
  }
  out={"schema":"hivenance_cross_market_propagation_autopsy_v1","coverage":{"events":len(ev)},"groups":{},
   "warning":"historical diagnosis only; groups are fixed descriptive relations, not promoted filters","execution_eligible":False,"promotion_eligible":False}
  for name,f in tests.items():
   rows=[e for e in ev if f(e)];early=[e["v"] for e in rows if e["era"]=="EARLY"];late=[e["v"] for e in rows if e["era"]=="LATE"]
   out["groups"][name]={"all":st([e["v"] for e in rows]),"early":st(early),"late":st(late),
    "delta_bps":round(statistics.fmean(late)-statistics.fmean(early),3) if early and late else None}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== CROSS-MARKET PROPAGATION AUTOPSY =====")
  print("events",len(ev))
  for name,r in out["groups"].items():
   print(f"{name:30s} early n={r['early']['n']:4d} {r['early']['mean_bps']:+8.3f} | late n={r['late']['n']:4d} {r['late']['mean_bps']:+8.3f} | delta={r['delta_bps']:+8.3f}")
  print(f"output: {a.output}\nHISTORICAL DIAGNOSIS ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
