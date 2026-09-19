#!/usr/bin/env python3
"""Temporal participation census over the frozen 1h-vs-24h conflict population.

Historical diagnosis only. No hour/session filter is searched or promoted.
All participation baselines use observations strictly before each event.
"""
from __future__ import annotations
import argparse,json,statistics,sys
from collections import defaultdict
from datetime import datetime,timezone
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
def q(x):
 if not x:return None
 return round(statistics.median(x),4)
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/temporal_participation_conflict_census.json");a=p.parse_args()
 m=MarketMemory(a.database);events=[]
 try:
  for s in SYMS:
   r=m.bars(s,"15m",limit=100000)
   hist=[]
   bee=TemporalParticipationBee(min_same_hour_samples=5)
   for i,row in enumerate(r):
    ts=int(row["open_ts_ms"])
    if i>=96 and i+4<len(r):
     px=float(row["close"]);r1=(px/float(r[i-4]["close"])-1)*10000;r24=(px/float(r[i-96]["close"])-1)*10000
     d1,d24=sg(r1),sg(r24)
     if d1 and d24 and d1!=d24:
      raw=(float(r[i+4]["close"])/px-1)*10000
      move15=(px/float(r[i-1]["close"])-1)*10000 if i else 0
      ev=bee.observe(observed_at_ms=ts,volume=float(row["volume"]),history=hist,realized_move_bps=move15)
      events.append({"s":s,"ts":ts,"v":-d1*raw,"hour":ev.utc_hour,"weekday":ev.weekday,"weekend":ev.weekend,
       "block":ev.utc_block_4h,"sessions":list(ev.session_proxies),"state":ev.activity_state,
       "vr":ev.volume_ratio_to_same_hour_median,"mr":ev.move_ratio_to_same_hour_median,"nbase":ev.historical_same_hour_n})
    move=(float(row["close"])/float(row["open"])-1)*10000 if float(row["open"]) else 0
    hist.append(ParticipationObservation(ts,float(row["volume"]),move))
  times=sorted({e["ts"] for e in events})
  fold_bounds=[]
  for k in range(5):
   lo=times[int(k*len(times)/5)];hi=times[int((k+1)*len(times)/5)-1];fold_bounds.append((lo,hi))
  out={"schema":"hivenance_temporal_participation_conflict_census_v1","coverage":{"events":len(events)},"by_utc_hour":{},"by_4h_block":{},
   "by_weekday":{},"by_weekend":{},"by_activity_state":{},"by_session_proxy":{},"folds":[],
   "warning":"historical diagnosis only; no hour/session/activity bucket is a promoted trading filter","execution_eligible":False,"promotion_eligible":False}
  groups={
   "by_utc_hour":lambda e:f"{e['hour']:02d}",
   "by_4h_block":lambda e:e["block"],
   "by_weekday":lambda e:str(e["weekday"]),
   "by_weekend":lambda e:"WEEKEND" if e["weekend"] else "WEEKDAY",
   "by_activity_state":lambda e:e["state"],
  }
  for name,key in groups.items():
   d=defaultdict(list)
   for e in events:d[key(e)].append(e)
   for k,rows in sorted(d.items()):
    x=st([e["v"] for e in rows]);x["median_volume_ratio"]=q([e["vr"] for e in rows if e["vr"] is not None]);out[name][k]=x
  sd=defaultdict(list)
  for e in events:
   for s in e["sessions"]:sd[s].append(e)
  for k,rows in sorted(sd.items()):
   x=st([e["v"] for e in rows]);x["median_volume_ratio"]=q([e["vr"] for e in rows if e["vr"] is not None]);out["by_session_proxy"][k]=x
  for idx,(lo,hi) in enumerate(fold_bounds,1):
   rows=[e for e in events if lo<=e["ts"]<=hi]
   hours=defaultdict(int);states=defaultdict(int);sessions=defaultdict(int)
   for e in rows:
    hours[e["hour"]]+=1;states[e["state"]]+=1
    for s in e["sessions"]:sessions[s]+=1
   out["folds"].append({"fold":idx,"start_ts":lo,"end_ts":hi,**st([e["v"] for e in rows]),
    "median_volume_ratio":q([e["vr"] for e in rows if e["vr"] is not None]),
    "hour_mix":{str(k):round(v/len(rows),4) for k,v in sorted(hours.items())},
    "activity_mix":{k:round(v/len(rows),4) for k,v in sorted(states.items())},
    "session_mix":{k:round(v/len(rows),4) for k,v in sorted(sessions.items())}})
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== TEMPORAL PARTICIPATION x FROZEN CONFLICT CENSUS =====")
  print("events",len(events))
  print("\n4H UTC BLOCKS")
  for k,v in out["by_4h_block"].items():print(f"{k:12s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f} volratio={v['median_volume_ratio']}")
  print("\nACTIVITY STATE")
  for k,v in out["by_activity_state"].items():print(f"{k:24s} n={v['n']:4d} mean={v['mean_bps']:+8.3f} med={v['median_bps']:+8.3f} win={v['win_rate']:.3f}")
  print("\nFOLDS + PARTICIPATION MIX")
  for f in out["folds"]:print(f"fold {f['fold']} n={f['n']:4d} mean={f['mean_bps']:+8.3f} medVR={f['median_volume_ratio']} activity={f['activity_mix']}")
  print(f"output: {a.output}\nHISTORICAL DIAGNOSIS ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
