#!/usr/bin/env python3
"""Test a fixed market-coherence explanation for the frozen conflict transition.

Uses only pre-event 15m OHLCV. Measures rolling 24h pairwise correlation,
realized-volatility level/change, cross-sectional dispersion and breadth.
Thresholds are NOT searched. Reports quartiles plus early/late within quartile.
Historical diagnosis only.
"""
from __future__ import annotations
import argparse,json,math,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
def sg(x,d=1):return 1 if x>d else -1 if x<-d else 0
def st(v):
 return {"n":len(v),"mean_bps":round(statistics.fmean(v),3) if v else 0,"median_bps":round(statistics.median(v),3) if v else 0,"win_rate":round(sum(x>0 for x in v)/len(v),4) if v else 0}
def corr(a,b):
 if len(a)<12 or len(a)!=len(b):return None
 ma,mb=statistics.fmean(a),statistics.fmean(b);sa=sum((x-ma)**2 for x in a);sb=sum((y-mb)**2 for y in b)
 if sa<=0 or sb<=0:return None
 return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(sa*sb)
def cuts(vals):
 x=sorted(vals);return [x[min(len(x)-1,int(k*len(x)/4))] for k in (1,2,3)]
def qb(x,c):return sum(x>z for z in c)
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/market_coherence_regime_autopsy.json");a=p.parse_args()
 m=MarketMemory(a.database)
 try:
  bars={s:m.bars(s,"15m",limit=100000) for s in SYMS};idx={s:{int(r["open_ts_ms"]):i for i,r in enumerate(rs)} for s,rs in bars.items()};ev=[]
  for s,rs in bars.items():
   for i in range(192,len(rs)-4):
    ts=int(rs[i]["open_ts_ms"]);px=float(rs[i]["close"]);r1=(px/float(rs[i-4]["close"])-1)*10000;r24=(px/float(rs[i-96]["close"])-1)*10000;d1,d24=sg(r1),sg(r24)
    if not d1 or not d24 or d1==d24:continue
    raw=(float(rs[i+4]["close"])/px-1)*10000
    series={};lastrets=[]
    for ps,prs in bars.items():
     j=idx[ps].get(ts)
     if j is None or j<192:continue
     x=[(float(prs[k]["close"])/float(prs[k-1]["close"])-1)*10000 for k in range(j-95,j+1)]
     series[ps]=x;lastrets.append(x[-1])
    cors=[]
    names=sorted(series)
    for u,x in enumerate(names):
     for y in names[u+1:]:
      c=corr(series[x],series[y])
      if c is not None:cors.append(c)
    own=series.get(s,[])
    vol24=statistics.pstdev(own) if len(own)>1 else 0
    volprev=statistics.pstdev([(float(rs[k]["close"])/float(rs[k-1]["close"])-1)*10000 for k in range(i-191,i-95)]) if i>=192 else 0
    ev.append({"s":s,"ts":ts,"v":-d1*raw,"corr":statistics.median(cors) if cors else 0,
      "vol":vol24,"vol_ratio":vol24/max(volprev,1e-12),"disp":statistics.pstdev(lastrets) if len(lastrets)>1 else 0,
      "breadth":sum(x>0 for x in lastrets)/len(lastrets) if lastrets else .5})
  times=sorted({e["ts"] for e in ev});bounds=[(times[int(k*len(times)/5)],times[int((k+1)*len(times)/5)-1]) for k in range(5)]
  for e in ev:e["fold"]=next(k+1 for k,(lo,hi) in enumerate(bounds) if lo<=e["ts"]<=hi);e["era"]="EARLY" if e["fold"]<=2 else "LATE"
  feats=["corr","vol","vol_ratio","disp","breadth"];out={"schema":"hivenance_market_coherence_regime_autopsy_v1","features":{},"fold_medians":{},
   "warning":"historical descriptive quartiles only; no threshold/filter promotion","execution_eligible":False,"promotion_eligible":False}
  for f in feats:
   c=cuts([e[f] for e in ev]);out["features"][f]={"cuts":c,"quartiles":{}}
   for q in range(4):
    rows=[e for e in ev if qb(e[f],c)==q];early=[e["v"] for e in rows if e["era"]=="EARLY"];late=[e["v"] for e in rows if e["era"]=="LATE"]
    out["features"][f]["quartiles"][str(q+1)]={"all":st([e["v"] for e in rows]),"early":st(early),"late":st(late),
      "delta_bps":round(statistics.fmean(late)-statistics.fmean(early),3) if early and late else None}
  for k in range(1,6):
   rows=[e for e in ev if e["fold"]==k];out["fold_medians"][str(k)]={f:round(statistics.median([e[f] for e in rows]),6) for f in feats}
  Path(a.output).write_text(json.dumps(out,indent=2))
  print("===== MARKET COHERENCE REGIME AUTOPSY =====")
  print("FOLD MEDIANS")
  for k,v in out["fold_medians"].items():print("fold",k,v)
  for f in feats:
   print("\n",f.upper(),"cuts",out["features"][f]["cuts"])
   for q,r in out["features"][f]["quartiles"].items():print(f"Q{q} early n={r['early']['n']:3d} {r['early']['mean_bps']:+8.3f} | late n={r['late']['n']:3d} {r['late']['mean_bps']:+8.3f} | delta={r['delta_bps']:+8.3f}")
  print(f"output: {a.output}\nHISTORICAL DIAGNOSIS ONLY | PRIVATE ORDERS: 0")
 finally:m.close()
if __name__=="__main__":main()
