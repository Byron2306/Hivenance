#!/usr/bin/env python3
"""Multivariate state matching for the frozen 1h-vs-24h conflict mechanism.

Matches EARLY events (folds 1-2) to LATE events (folds 3-5) on pre-event market
state jointly: rolling correlation, volatility, volatility ratio, dispersion,
breadth, UTC block, symbol, |1h| and |24h| displacement. Nearest-neighbor
matching is diagnostic only and does not create a trading rule.
"""
from __future__ import annotations
import argparse,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def sg(x,d=1):return 1 if x>d else -1 if x<-d else 0
def corr(a,b):
 if len(a)<12:return 0.0
 ma,mb=statistics.fmean(a),statistics.fmean(b);sa=sum((x-ma)**2 for x in a);sb=sum((y-mb)**2 for y in b)
 return 0.0 if sa<=0 or sb<=0 else sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(sa*sb)
def medmad(vals):
 med=statistics.median(vals);mad=statistics.median(abs(x-med) for x in vals);return med,max(mad,1e-9)
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/multivariate_state_match.json");p.add_argument("--caliper",type=float,default=3.0);a=p.parse_args()
 m=MarketMemory(a.database)
 try:
  bars={s:m.bars(s,"15m",limit=100000) for s in SYMS};idx={s:{int(r["open_ts_ms"]):i for i,r in enumerate(rs)} for s,rs in bars.items()};ev=[]
  for s,rs in bars.items():
   for i in range(192,len(rs)-4):
    ts=int(rs[i]["open_ts_ms"]);px=float(rs[i]["close"]);r1=(px/float(rs[i-4]["close"])-1)*10000;r24=(px/float(rs[i-96]["close"])-1)*10000;d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(rs[i+4]["close"])/px-1)*10000;series={};last=[]
    for ps,prs in bars.items():
     j=idx[ps].get(ts)
     if j is None or j<192:continue
     x=[(float(prs[k]["close"])/float(prs[k-1]["close"])-1)*10000 for k in range(j-95,j+1)];series[ps]=x;last.append(x[-1])
    cors=[];names=sorted(series)
    for u,x in enumerate(names):
     for y in names[u+1:]:cors.append(corr(series[x],series[y]))
    own=series[s];vol=statistics.pstdev(own);prev=[(float(rs[k]["close"])/float(rs[k-1]["close"])-1)*10000 for k in range(i-191,i-95)]
    ev.append({"s":s,"ts":ts,"v":-d1*raw,"corr":statistics.median(cors),"vol":vol,"vr":vol/max(statistics.pstdev(prev),1e-9),
      "disp":statistics.pstdev(last),"breadth":sum(x>0 for x in last)/len(last),"block":(ts//3600000%24)//4,"a1":abs(r1),"a24":abs(r24)})
  times=sorted({e["ts"] for e in ev});bounds=[(times[int(k*len(times)/5)],times[int((k+1)*len(times)/5)-1]) for k in range(5)]
  for e in ev:e["fold"]=next(k+1 for k,(lo,hi) in enumerate(bounds) if lo<=e["ts"]<=hi);e["era"]="E" if e["fold"]<=2 else "L"
  feats=["corr","vol","vr","disp","breadth","a1","a24"];scale={f:medmad([e[f] for e in ev]) for f in feats}
  def dist(x,y):
   d=sum(((x[f]-y[f])/scale[f][1])**2 for f in feats)
   d+=0 if x["block"]==y["block"] else 1.0
   return math.sqrt(d)
  early=[e for e in ev if e["era"]=="E"];late=[e for e in ev if e["era"]=="L"];used=set();pairs=[]
  # exact symbol, nearest state, no replacement
  for x in sorted(early,key=lambda z:z["ts"]):
   cand=[(dist(x,y),j,y) for j,y in enumerate(late) if j not in used and y["s"]==x["s"]]
   if not cand:continue
   d,j,y=min(cand,key=lambda z:z[0])
   if d<=a.caliper:used.add(j);pairs.append((x,y,d))
  gaps=[y["v"]-x["v"] for x,y,d in pairs]
  bysym={}
  for s in SYMS:
   ps=[p for p in pairs if p[0]["s"]==s];gs=[y["v"]-x["v"] for x,y,d in ps]
   bysym[s]={"pairs":len(ps),"early_mean_bps":round(statistics.fmean([x["v"] for x,y,d in ps]),3) if ps else None,
    "late_mean_bps":round(statistics.fmean([y["v"] for x,y,d in ps]),3) if ps else None,"paired_gap_bps":round(statistics.fmean(gs),3) if gs else None}
  balance={}
  for f in feats:
   ex=[x[f] for x,y,d in pairs];ly=[y[f] for x,y,d in pairs];balance[f]={"early_median":round(statistics.median(ex),6),"late_median":round(statistics.median(ly),6),
    "median_abs_pair_diff":round(statistics.median(abs(y[f]-x[f]) for x,y,d in pairs),6)}
  out={"schema":"hivenance_multivariate_state_match_v1","caliper":a.caliper,"early_events":len(early),"late_events":len(late),"matched_pairs":len(pairs),
    "coverage_early":round(len(pairs)/len(early),4),"early_mean_bps":round(statistics.fmean([x["v"] for x,y,d in pairs]),3) if pairs else None,
    "late_mean_bps":round(statistics.fmean([y["v"] for x,y,d in pairs]),3) if pairs else None,"paired_gap_bps":round(statistics.fmean(gaps),3) if gaps else None,
    "median_match_distance":round(statistics.median(d for x,y,d in pairs),3) if pairs else None,"balance":balance,"per_symbol":bysym,
    "warning":"historical nearest-neighbor diagnosis only; matching variables/caliper are not a trading filter or prospective proof","execution_eligible":False,"promotion_eligible":False}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== MULTIVARIATE MARKET-STATE MATCH =====")
  print({k:out[k] for k in ["early_events","late_events","matched_pairs","coverage_early","early_mean_bps","late_mean_bps","paired_gap_bps","median_match_distance"]})
  print("\nBALANCE");[print(f"{f:8s}",v) for f,v in balance.items()]
  print("\nPER SYMBOL");[print(f"{s:9s}",v) for s,v in bysym.items()]
  print(f"output: {a.output}\nHISTORICAL MATCHING ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
