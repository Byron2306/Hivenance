#!/usr/bin/env python3
"""Frozen temporal mechanism walk-forward and placebo gauntlet.

No threshold search. Tests the already-discovered rule across chronological folds,
symbol holdouts, time-shift placebos, sign placebo and market-episode aggregation.
Historical falsification only.
"""
from __future__ import annotations
import argparse,json,random,statistics,sys
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
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/temporal_walkforward_placebo.json");a=p.parse_args()
 m=MarketMemory(a.database);ev=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   for i in range(96,len(r)-4):
    px=float(r[i]["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000
    d1,d24=sg(r1),sg(r24)
    if not d1 or not d24:continue
    raw=(float(r[i+4]["close"])/px-1)*10000
    ev.append({"s":s,"ts":int(r[i]["open_ts_ms"]),"conflict":d1!=d24,"v":-d1*raw,"raw":raw})
  cf=[e for e in ev if e["conflict"]];times=sorted({e["ts"] for e in cf})
  folds=[]
  for k in range(5):
   lo=times[int(k*len(times)/5)];hi=times[int((k+1)*len(times)/5)-1]
   x=[e["v"] for e in cf if lo<=e["ts"]<=hi];folds.append({"fold":k+1,"start_ts":lo,"end_ts":hi,**st(x)})
  # Placebo: shift the conflict admission mask forward/backward while preserving outcomes.
  bys={}
  for e in ev:bys.setdefault(e["s"],[]).append(e)
  placebo={}
  for shift in (-16,-8,-4,4,8,16): # 15m bars
   vals=[]
   for s,rows in bys.items():
    rows=sorted(rows,key=lambda z:z["ts"])
    for i,e in enumerate(rows):
     j=i+shift
     if 0<=j<len(rows) and rows[j]["conflict"]:vals.append(e["v"])
   placebo[f"shift_{shift*15}m"]=st(vals)
  # Deterministic random admission with same per-symbol conflict count.
  rng=random.Random(2306);rand=[]
  for s,rows in bys.items():
   n=sum(e["conflict"] for e in rows);sample=rng.sample(rows,min(n,len(rows)));rand.extend(e["v"] for e in sample)
  # Equal-weight hourly episodes for each chronological fold.
  episode_folds=[]
  for f in folds:
   eps={}
   for e in cf:
    if f["start_ts"]<=e["ts"]<=f["end_ts"]:eps.setdefault(e["ts"]//3600000,[]).append(e["v"])
   episode_folds.append({"fold":f["fold"],**st([statistics.fmean(v) for v in eps.values()])})
  out={"schema":"hivenance_temporal_walkforward_placebo_v1","chronological_folds":folds,"episode_folds":episode_folds,
   "placebo_time_shifts":placebo,"random_same_count":st(rand),"sign_inversion":st([-e["v"] for e in cf]),
   "symbol_holdouts":{s:st([e["v"] for e in cf if e["s"]!=s]) for s in SYMS},
   "note":"frozen historical falsification; folds are evaluation slices, not prospective evidence","execution_eligible":False}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== WALK-FORWARD + PLACEBO GAUNTLET =====")
  print("\nCHRONOLOGICAL FOLDS");[print(f"fold {x['fold']} n={x['n']:4d} mean={x['mean_bps']:+8.3f} med={x['median_bps']:+8.3f} win={x['win_rate']:.3f}") for x in folds]
  print("\nEPISODE FOLDS");[print(f"fold {x['fold']} n={x['n']:4d} mean={x['mean_bps']:+8.3f} med={x['median_bps']:+8.3f} win={x['win_rate']:.3f}") for x in episode_folds]
  print("\nTIME-SHIFT PLACEBOS");[print(f"{k:12s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} win={v['win_rate']:.3f}") for k,v in placebo.items()]
  print("\nRANDOM SAME COUNT",out["random_same_count"]);print("SIGN INVERSION",out["sign_inversion"])
  print("\nSYMBOL HOLDOUTS");[print(f"without {s:9s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}") for s,v in out["symbol_holdouts"].items()]
  print(f"output: {a.output}\nHISTORICAL FALSIFICATION ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
