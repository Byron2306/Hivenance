#!/usr/bin/env python3
"""Transition-window market-state autopsy around the frozen conflict change point.

Uses only public OHLCV already in MarketMemory. Compares the 24h before/after
2026-09-15 10:00 UTC across return, range, realized volatility, volume, candle
body/wick geometry, correlation, dispersion and breadth. Descriptive only.
"""
from __future__ import annotations
import argparse,json,math,statistics,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def st(v):
 return {"n":len(v),"mean":round(statistics.fmean(v),6) if v else None,"median":round(statistics.median(v),6) if v else None}
def corr(a,b):
 if len(a)<3 or len(a)!=len(b):return None
 ma,mb=statistics.fmean(a),statistics.fmean(b);sa=sum((x-ma)**2 for x in a);sb=sum((y-mb)**2 for y in b)
 if sa<=0 or sb<=0:return None
 return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(sa*sb)
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/transition_window_market_state_autopsy.json");a=p.parse_args()
 cp=int(datetime(2026,9,15,10,0,tzinfo=timezone.utc).timestamp()*1000);m=MarketMemory(a.database)
 try:
  bars={s:m.bars(s,"15m",limit=100000) for s in SYMS};out={"schema":"hivenance_transition_window_market_state_autopsy_v1","boundary_utc":"2026-09-15 10:00",
   "per_symbol":{},"market":{},"warning":"descriptive historical autopsy only; no feature is a promoted filter","execution_eligible":False,"promotion_eligible":False}
  periods={"PRE24H":(cp-24*3600000,cp),"POST24H":(cp,cp+24*3600000)}
  period_returns={}
  for label,(lo,hi) in periods.items():
   period_returns[label]={};market_rows=[]
   for s,rows in bars.items():
    rr=[r for r in rows if lo<=int(r["open_ts_ms"])<hi];rets=[];vols=[];ranges=[];bodies=[];upper=[];lower=[]
    for r in rr:
     o,h,l,c,v=map(float,(r["open"],r["high"],r["low"],r["close"],r["volume"]))
     if o<=0:continue
     rets.append((c/o-1)*10000);vols.append(v);ranges.append((h/l-1)*10000 if l>0 else 0);bodies.append(abs(c/o-1)*10000)
     den=max(h-l,1e-12);upper.append((h-max(o,c))/den);lower.append((min(o,c)-l)/den)
    period_returns[label][s]=rets
    rec={"return_bps":round(sum(rets),3),"realized_vol_bps":round(statistics.pstdev(rets),3) if len(rets)>1 else 0,
      "volume":st(vols),"range_bps":st(ranges),"body_bps":st(bodies),"upper_wick_fraction":st(upper),"lower_wick_fraction":st(lower)}
    out["per_symbol"].setdefault(s,{})[label]=rec;market_rows.extend(rets)
   # same-timestamp breadth, dispersion and pairwise correlation
   byts={}
   for s,rows in bars.items():
    for r in rows:
     ts=int(r["open_ts_ms"])
     if lo<=ts<hi and float(r["open"])>0:byts.setdefault(ts,{})[s]=(float(r["close"])/float(r["open"])-1)*10000
   breadth=[];disp=[]
   for vals in byts.values():
    xs=list(vals.values())
    if xs:breadth.append(sum(x>0 for x in xs)/len(xs));disp.append(statistics.pstdev(xs) if len(xs)>1 else 0)
   cors=[]
   for i,s1 in enumerate(SYMS):
    for s2 in SYMS[i+1:]:
     pairs=[]
     for ts,vals in byts.items():
      if s1 in vals and s2 in vals:pairs.append((vals[s1],vals[s2]))
     c=corr([x for x,_ in pairs],[y for _,y in pairs])
     if c is not None:cors.append(c)
   out["market"][label]={"breadth_positive_fraction":st(breadth),"cross_section_dispersion_bps":st(disp),"pairwise_return_correlation":st(cors)}
  # explicit deltas
  out["deltas"]={}
  for s in SYMS:
   pre=out["per_symbol"][s]["PRE24H"];post=out["per_symbol"][s]["POST24H"]
   out["deltas"][s]={"return_bps":round(post["return_bps"]-pre["return_bps"],3),"realized_vol_bps":round(post["realized_vol_bps"]-pre["realized_vol_bps"],3),
    "median_volume_ratio":round(post["volume"]["median"]/pre["volume"]["median"],3) if pre["volume"]["median"] else None,
    "median_range_ratio":round(post["range_bps"]["median"]/pre["range_bps"]["median"],3) if pre["range_bps"]["median"] else None}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== TRANSITION-WINDOW MARKET-STATE AUTOPSY =====")
  print("boundary 2026-09-15 10:00 UTC")
  print("\nMARKET STRUCTURE")
  for k,v in out["market"].items():print(k,v)
  print("\nPER SYMBOL DELTAS POST24H - PRE24H")
  for s,d in out["deltas"].items():print(f"{s:9s} returnΔ={d['return_bps']:+9.3f} volΔ={d['realized_vol_bps']:+8.3f} volume×={d['median_volume_ratio']} range×={d['median_range_ratio']}")
  print(f"output: {a.output}\nHISTORICAL DIAGNOSIS ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
