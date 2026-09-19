#!/usr/bin/env python3
"""Decompose whether participation topology explains the frozen conflict fold split.

Historical diagnosis only. No bucket/filter is optimized or promoted.
Uses fixed 4h UTC blocks and fixed activity states already defined before this test.
Reports fold x block, fold x activity, within-stratum early-vs-late deltas, and a
composition-standardized estimate using pooled stratum weights.
"""
from __future__ import annotations
import argparse,json,statistics,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
from strategies.relative_value_lab.temporal_participation_bee import ParticipationObservation,TemporalParticipationBee
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def sg(x,d=1):return 1 if x>d else -1 if x<-d else 0
def st(v):
 return {"n":len(v),"mean_bps":round(statistics.fmean(v),3) if v else 0,"median_bps":round(statistics.median(v),3) if v else 0,
 "win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0}
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/temporal_participation_fold_decomposition.json");a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   rows=m.bars(s,"15m",limit=100000);hist=[];bee=TemporalParticipationBee(min_same_hour_samples=5)
   for i,row in enumerate(rows):
    ts=int(row["open_ts_ms"])
    if i>=96 and i+4<len(rows):
     px=float(row["close"]);r1=(px/float(rows[i-4]["close"])-1)*10000;r24=(px/float(rows[i-96]["close"])-1)*10000;d1,d24=sg(r1),sg(r24)
     if d1 and d24 and d1!=d24:
      raw=(float(rows[i+4]["close"])/px-1)*10000
      move=(px/float(rows[i-1]["close"])-1)*10000 if i else 0
      pe=bee.observe(observed_at_ms=ts,volume=float(row["volume"]),history=hist,realized_move_bps=move)
      ev.append({"s":s,"ts":ts,"v":-d1*raw,"block":pe.utc_block_4h,"activity":pe.activity_state})
    move=(float(row["close"])/float(row["open"])-1)*10000 if float(row["open"]) else 0
    hist.append(ParticipationObservation(ts,float(row["volume"]),move))
  times=sorted({e["ts"] for e in ev});bounds=[]
  for k in range(5):
   bounds.append((times[int(k*len(times)/5)],times[int((k+1)*len(times)/5)-1]))
  for e in ev:
   e["fold"]=next(k+1 for k,(lo,hi) in enumerate(bounds) if lo<=e["ts"]<=hi)
   e["era"]="EARLY" if e["fold"]<=2 else "LATE"
   e["stratum"]=e["block"]+"|"+e["activity"]
  out={"schema":"hivenance_temporal_participation_fold_decomposition_v1","fold_x_block":{},"fold_x_activity":{},"early_vs_late_within_stratum":{},
   "standardization":{},"warning":"historical decomposition only; no stratum is a promoted filter","execution_eligible":False,"promotion_eligible":False}
  for fold in range(1,6):
   fr=[e for e in ev if e["fold"]==fold]
   out["fold_x_block"][str(fold)]={k:st([e["v"] for e in fr if e["block"]==k]) for k in sorted({e["block"] for e in ev})}
   out["fold_x_activity"][str(fold)]={k:st([e["v"] for e in fr if e["activity"]==k]) for k in sorted({e["activity"] for e in ev})}
  strata=sorted({e["stratum"] for e in ev})
  pooled={z:sum(e["stratum"]==z for e in ev)/len(ev) for z in strata}
  usable=[]
  for z in strata:
   early=[e["v"] for e in ev if e["stratum"]==z and e["era"]=="EARLY"];late=[e["v"] for e in ev if e["stratum"]==z and e["era"]=="LATE"]
   rec={"early":st(early),"late":st(late),"pooled_weight":round(pooled[z],6)}
   rec["late_minus_early_mean_bps"]=round(statistics.fmean(late)-statistics.fmean(early),3) if early and late else None
   out["early_vs_late_within_stratum"][z]=rec
   if early and late:usable.append(z)
  weight=sum(pooled[z] for z in usable)
  early_std=sum((pooled[z]/weight)*statistics.fmean([e["v"] for e in ev if e["stratum"]==z and e["era"]=="EARLY"]) for z in usable) if weight else 0
  late_std=sum((pooled[z]/weight)*statistics.fmean([e["v"] for e in ev if e["stratum"]==z and e["era"]=="LATE"]) for z in usable) if weight else 0
  actual_early=statistics.fmean([e["v"] for e in ev if e["era"]=="EARLY"]);actual_late=statistics.fmean([e["v"] for e in ev if e["era"]=="LATE"])
  out["standardization"]={"usable_strata":len(usable),"total_strata":len(strata),"pooled_weight_covered":round(weight,6),
   "actual_early_mean_bps":round(actual_early,3),"actual_late_mean_bps":round(actual_late,3),"actual_gap_bps":round(actual_late-actual_early,3),
   "composition_standardized_early_mean_bps":round(early_std,3),"composition_standardized_late_mean_bps":round(late_std,3),
   "standardized_gap_bps":round(late_std-early_std,3),
   "interpretation":"If standardized gap remains large, changing participation composition alone does not explain the regime split."}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== TEMPORAL PARTICIPATION FOLD DECOMPOSITION =====")
  print("STANDARDIZATION",out["standardization"])
  print("\nWITHIN-STRATUM EARLY -> LATE")
  for z,r in out["early_vs_late_within_stratum"].items():
   if r["late_minus_early_mean_bps"] is not None and r["early"]["n"]>=10 and r["late"]["n"]>=10:
    print(f"{z:42s} early n={r['early']['n']:3d} {r['early']['mean_bps']:+8.3f} | late n={r['late']['n']:3d} {r['late']['mean_bps']:+8.3f} | delta={r['late_minus_early_mean_bps']:+8.3f}")
  print(f"output: {a.output}\nHISTORICAL DECOMPOSITION ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
