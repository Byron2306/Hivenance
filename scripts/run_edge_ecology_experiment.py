#!/usr/bin/env python3
"""Public-data Edge Ecology experiment for Termux.

Collects Kraken spot trades + order books, builds FLOW/LIQUIDITY/TREND/VOLATILITY
voices, freezes a pre-outcome hypothesis, then settles it after a fixed horizon.
No authenticated endpoint and no order path are present.
"""
from __future__ import annotations
import argparse, json, math, statistics, sys, time
from collections import deque
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from agents.kraken_public_rest import KrakenPublicRestClient
from strategies.relative_value_lab.edge_ecology import EdgeEcology
from strategies.relative_value_lab.metatron_ml_challenger import MetatronMLChallenger

def mid(book):
    b=(book.get("bids") or [[0]])[0][0]; a=(book.get("asks") or [[0]])[0][0]
    return (float(a)+float(b))/2 if a and b else 0.0

def depth(book, side):
    return sum(float(p)*float(q) for p,q,*_ in (book.get(side) or []))

def stats(vals):
    vals=list(vals); wins=sum(v>0 for v in vals)
    eq=peak=dd=0.0
    for v in vals:
        eq+=v; peak=max(peak,eq); dd=max(dd,peak-eq)
    return {"n":len(vals),"net_bps":round(sum(vals),4),"mean_bps":round(statistics.fmean(vals),4) if vals else 0.0,
            "win_rate":round(wins/len(vals),4) if vals else 0.0,"max_drawdown_bps":round(dd,4)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--symbol",default="BTC/USD"); ap.add_argument("--duration-sec",type=int,default=3600)
    ap.add_argument("--interval-sec",type=float,default=5.0); ap.add_argument("--horizon-sec",type=int,default=30)
    ap.add_argument("--output",type=Path,default=ROOT/"data/edge_ecology_experiment.json")
    ap.add_argument("--cost-bps",type=float,default=0.0,help="round-trip research cost assumption")
    args=ap.parse_args()
    c=KrakenPublicRestClient(); c.load_markets(); eco=EdgeEcology()
    hist=deque(maxlen=120); pending=[]; settled=[]; training=[]; ml=None
    prev_flow=0.0; prev_bd=prev_ad=None; started=time.monotonic(); cycle=0
    while time.monotonic()-started < args.duration_sec:
        t0=time.monotonic(); cycle+=1; ts=int(time.time()*1000)
        book=c.fetch_order_book(args.symbol,limit=25); px=mid(book)
        trades=c.fetch_trades(args.symbol,limit=200)
        cutoff=ts-int(max(10,args.interval_sec*3)*1000)
        recent=[x for x in trades if int(x.get("timestamp") or 0)>=cutoff]
        buy=sum(float(x.get("amount") or 0) for x in recent if str(x.get("side")).lower()=="buy")
        sell=sum(float(x.get("amount") or 0) for x in recent if str(x.get("side")).lower()=="sell")
        bd,ad=depth(book,"bids"),depth(book,"asks")
        bids=book.get("bids") or []; asks=book.get("asks") or []
        spread=((float(asks[0][0])-float(bids[0][0]))/px*10000) if px and bids and asks else 0.0
        hist.append(px)
        rets=[(hist[i]/hist[i-1]-1.0) for i in range(1,len(hist)) if hist[i-1]]
        fv=eco.flow_voice(taker_buy_volume=buy,taker_sell_volume=sell,previous_imbalance=prev_flow)
        lv=eco.liquidity_voice(bid_depth=bd,ask_depth=ad,spread_bps=spread,previous_bid_depth=prev_bd,previous_ask_depth=prev_ad)
        tv=eco.trend_voice(returns=rets[-12:]); vv=eco.volatility_voice(returns=rets[-30:],baseline_vol=statistics.pstdev(rets) if len(rets)>2 else None)
        snap=eco.snapshot(timestamp_ms=ts,pair_id=args.symbol,voices=[fv,lv,tv,vv])
        feature=[fv.score,lv.score,tv.score,vv.score,spread/10.0]
        training.append(feature)
        if ml is None and len(training)>=40:
            ml=MetatronMLChallenger(seed=2306); ml.fit(training[:40])
        challenge=ml.challenge(feature) if ml else None
        exhaustion=fv.state=="AGGRESSIVE_FLOW_EXHAUSTING"
        liquid=lv.state!="LIQUIDITY_FRAGILE"
        trend_persistent=tv.state=="TREND_PERSISTENT"
        direction=-1 if prev_flow>0 else 1
        variants={
          "FLOW_ONLY": exhaustion,
          "FLOW_LIQUIDITY": exhaustion and liquid,
          "FLOW_LIQUIDITY_TREND_GUARD": exhaustion and liquid and not trend_persistent,
          "ML_CHALLENGER": exhaustion and liquid and challenge is not None and challenge.regime!="NOVEL_STATE",
          "FULL_EDGE_ECOLOGY": exhaustion and liquid and not trend_persistent and (challenge is None or challenge.regime!="NOVEL_STATE"),
          "HASH_MATCHED": (hash(f"{args.symbol}:{ts//1000}")%4)==0,
        }
        if px and any(variants.values()):
            pending.append({"ts":ts,"due":ts+args.horizon_sec*1000,"px":px,"dir":direction,"variants":variants,
                            "snapshot":snap.to_dict(),"ml":None if challenge is None else challenge.to_dict()})
        still=[]
        for p in pending:
            if ts<p["due"]: still.append(p); continue
            gross=p["dir"]*((px/p["px"])-1.0)*10000.0; net=gross-args.cost_bps
            settled.append({"forecast_ts":p["ts"],"settled_ts":ts,"gross_bps":gross,"net_bps":net,**p})
        pending=still
        prev_flow=fv.features["imbalance"]; prev_bd,prev_ad=bd,ad
        books={k:stats(x["net_bps"] for x in settled if x["variants"].get(k)) for k in variants}
        print(f"EDGE_ECOLOGY cycle={cycle} px={px:.2f} flow={fv.state} liq={lv.state} trend={tv.state} ml={challenge.regime if challenge else 'WARMUP'} settled={len(settled)} full_n={books['FULL_EDGE_ECOLOGY']['n']} full_net={books['FULL_EDGE_ECOLOGY']['net_bps']:+.3f}bps orders=0",flush=True)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps({"schema":"hivenance_edge_ecology_experiment_v1","symbol":args.symbol,"horizon_sec":args.horizon_sec,
          "cost_bps":args.cost_bps,"books":books,"settled":settled,"private_orders":0,"execution_eligible":False,"promotion_eligible":False},indent=2,default=str))
        time.sleep(max(0.1,args.interval_sec-(time.monotonic()-t0)))
    return 0
if __name__=="__main__": raise SystemExit(main())
