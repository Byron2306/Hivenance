#!/usr/bin/env python3
"""Historical World-State replay and first temporal ablation laboratory."""
from __future__ import annotations
import argparse,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from agents.market_memory import MarketMemory
from agents.world_state import WorldStateBuilder

SYMS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
H=(15,60,240,1440)

def sign(x,dead=1.0):return 1 if x is not None and x>dead else -1 if x is not None and x<-dead else 0
def stats(xs):
    return {"n":len(xs),"net_bps":round(sum(xs),4),"mean_bps":round(statistics.fmean(xs),4) if xs else 0,
            "win_rate":round(sum(x>0 for x in xs)/len(xs),4) if xs else 0}

def main():
    p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db")
    p.add_argument("--step-min",type=int,default=60);p.add_argument("--cost-bps",type=float,default=0.0)
    p.add_argument("--output",default="data/world_state_temporal_ablation.json");a=p.parse_args()
    m=MarketMemory(a.database);b=WorldStateBuilder(m); books={}; rows=[]
    try:
        base=m.bars("BTC/USD","1m",limit=100000)
        if len(base)<400: raise SystemExit("not enough 1m memory")
        timestamps=[int(r["open_ts_ms"]) for r in base[60:-5:max(1,a.step_min)]]
        for ts in timestamps:
            pages={}
            for s in SYMS:
                try: pages[s]=b.build(s,ts,SYMS)
                except ValueError: pass
            if len(pages)<2:continue
            # Cross-sectional selector: rank absolute 1h movement. This is a
            # diagnostic baseline, not a claimed strategy.
            ranked=sorted(pages.values(),key=lambda p:abs(float(p.temporal["1h_bps"] or 0)),reverse=True)
            for page in ranked:
                one=m.bars(page.symbol,"1m",limit=100000)
                idx=next((i for i,r in enumerate(one) if int(r["open_ts_ms"])==ts),None)
                if idx is None:continue
                for hm in H:
                    if idx+hm>=len(one):continue
                    p0=float(one[idx]["close"]);p1=float(one[idx+hm]["close"])
                    raw=(p1/p0-1)*10000 if p0>0 else 0
                    dirs={
                      "FOLLOW_1H":sign(page.temporal["1h_bps"]),
                      "REVERT_1H":-sign(page.temporal["1h_bps"]),
                      "FOLLOW_24H":sign(page.temporal["24h_bps"]),
                      "REVERT_24H":-sign(page.temporal["24h_bps"]),
                      "ALIGN_1H_24H":sign(page.temporal["1h_bps"]) if sign(page.temporal["1h_bps"])==sign(page.temporal["24h_bps"]) else 0,
                      "CONFLICT_REVERT_1H":-sign(page.temporal["1h_bps"]) if sign(page.temporal["1h_bps"])!=sign(page.temporal["24h_bps"]) else 0,
                    }
                    for name,d in dirs.items():
                        if d:
                            val=d*raw-a.cost_bps;books.setdefault(f"{name}_H{hm}m",[]).append(val)
                    rows.append({"world_state_id":page.world_state_id,"ts":ts,"symbol":page.symbol,
                                 "rank":ranked.index(page)+1,"horizon_min":hm,"future_raw_bps":raw,
                                 "temporal":page.temporal})
        out={"schema":"hivenance_world_state_temporal_ablation_v1","cost_bps":a.cost_bps,
             "books":{k:stats(v) for k,v in books.items()},"rows":rows,
             "note":"historical discovery evidence only; not prospective proof",
             "execution_eligible":False,"promotion_eligible":False}
        Path(a.output).write_text(json.dumps(out,indent=2))
        for k,v in sorted(out["books"].items(),key=lambda kv:kv[1]["mean_bps"],reverse=True):
            print(f"{k:28s} n={v['n']:5d} net={v['net_bps']:+10.3f} mean={v['mean_bps']:+8.3f} win={v['win_rate']:.3f}")
        print(f"output: {a.output}");print("HISTORICAL DISCOVERY ONLY | PRIVATE ORDERS: 0")
    finally:m.close()
    return 0
if __name__=="__main__":raise SystemExit(main())
