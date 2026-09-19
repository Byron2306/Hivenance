#!/usr/bin/env python3
"""Long-window temporal replay using canonical Market Memory.

Uses the coarsest suitable stored bar series for each forward horizon so replay is
not constrained by the ~720-row 1m window. Historical discovery only.
"""
from __future__ import annotations
import argparse,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory

SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
HOLD={"15m":15,"1h":60,"4h":240,"24h":1440}
TF_MIN={"1m":1,"5m":5,"15m":15,"1h":60,"4h":240,"1d":1440}
REPLAY_TF={"15m":"5m","1h":"15m","4h":"1h","24h":"4h"}

def sg(x,d=1.0):return 1 if x is not None and x>d else -1 if x is not None and x<-d else 0
def ret(rows,i,bars):
    if i-bars<0:return None
    a=float(rows[i-bars]["close"]);b=float(rows[i]["close"])
    return (b/a-1)*10000 if a>0 and b>0 else None
def future(rows,i,bars):
    if i+bars>=len(rows):return None
    a=float(rows[i]["close"]);b=float(rows[i+bars]["close"])
    return (b/a-1)*10000 if a>0 and b>0 else None
def stat(xs):
    return {"n":len(xs),"net_bps":round(sum(xs),4),"mean_bps":round(statistics.fmean(xs),4) if xs else 0,
      "median_bps":round(statistics.median(xs),4) if xs else 0,"win_rate":round(sum(x>0 for x in xs)/len(xs),4) if xs else 0}
def bucket(age_days):
    if age_days<=7:return "LAST_7D"
    if age_days<=31:return "8_31D"
    if age_days<=183:return "1_6M"
    if age_days<=366:return "6_12M"
    return "GT_1Y"

def main():
    p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db")
    p.add_argument("--cost-bps",type=float,default=0);p.add_argument("--output",default="data/temporal_long_window_ablation.json")
    a=p.parse_args();m=MarketMemory(a.database);books={};per_symbol={};per_bucket={};rows_out=[]
    try:
      newest=max(int(r["open_ts_ms"]) for s in SYMS for r in m.bars(s,"1d",limit=100000))
      for hold_name,hold_min in HOLD.items():
        tf=REPLAY_TF[hold_name];step=TF_MIN[tf];hbars=max(1,hold_min//step)
        oneh=max(1,60//step);day=max(1,1440//step)
        for sym in SYMS:
          rows=m.bars(sym,tf,limit=100000)
          for i in range(max(oneh,day),len(rows)-hbars):
            ts=int(rows[i]["open_ts_ms"]); r1=ret(rows,i,oneh);r24=ret(rows,i,day)
            d1,d24=sg(r1),sg(r24)
            if not d1 or not d24:continue
            raw=future(rows,i,hbars)
            if raw is None:continue
            age=(newest-ts)/86400000
            vals={
              "REVERT_1H":-d1*raw-a.cost_bps,
              "FOLLOW_24H":d24*raw-a.cost_bps,
            }
            if d1!=d24: vals["CONFLICT_REVERT_1H"]=-d1*raw-a.cost_bps
            else: vals["ALIGN_1H_24H"]=d1*raw-a.cost_bps
            for name,val in vals.items():
              key=f"{name}_{hold_name}";books.setdefault(key,[]).append(val)
              per_symbol.setdefault(sym,{}).setdefault(key,[]).append(val)
              per_bucket.setdefault(bucket(age),{}).setdefault(key,[]).append(val)
            rows_out.append({"ts":ts,"symbol":sym,"age_days":round(age,3),"bucket":bucket(age),
              "replay_timeframe":tf,"hold":hold_name,"r1h_bps":r1,"r24h_bps":r24,"future_raw_bps":raw})
      out={"schema":"hivenance_temporal_long_window_ablation_v1","cost_bps":a.cost_bps,
        "books":{k:stat(v) for k,v in books.items()},
        "per_symbol":{s:{k:stat(v) for k,v in d.items()} for s,d in per_symbol.items()},
        "time_buckets":{b:{k:stat(v) for k,v in d.items()} for b,d in per_bucket.items()},
        "rows":rows_out,"note":"historical discovery only; overlapping observations and correlated assets are not independent",
        "execution_eligible":False,"promotion_eligible":False}
      Path(a.output).write_text(json.dumps(out,indent=2))
      print("===== LONG-WINDOW TEMPORAL ABLATION =====")
      for b,d in out["time_buckets"].items():
        print(f"\n--- {b} ---")
        for k,v in sorted(d.items()):
          if k.startswith("CONFLICT_REVERT"):
            print(f"{k:30s} n={v['n']:5d} net={v['net_bps']:+10.2f} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
      print("\n--- ALL HISTORY ---")
      for k,v in sorted(out["books"].items()):
        if k.startswith("CONFLICT_REVERT"):
          print(f"{k:30s} n={v['n']:5d} net={v['net_bps']:+10.2f} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
      print(f"output: {a.output}");print("HISTORICAL DISCOVERY ONLY | PRIVATE ORDERS: 0")
    finally:m.close()
    return 0
if __name__=="__main__":raise SystemExit(main())
