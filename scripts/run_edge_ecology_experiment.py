#!/usr/bin/env python3
"""Edge Ecology v2: preregistered multi-horizon public-market experiment.

Scientific goals:
* preserve every observation, not only admitted rows;
* compare exhaustion vs persistence and reversion vs continuation;
* expose each organ's marginal veto/admit effect;
* use deterministic SHA-256 controls count-matched offline to each selector;
* freeze 15/30/60/120 second horizons at observation time.

Research only. No authenticated endpoints, orders, execution or promotion.
"""
from __future__ import annotations
import argparse, hashlib, json, statistics, sys, time
from collections import deque
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from agents.kraken_public_rest import KrakenPublicRestClient
from strategies.relative_value_lab.edge_ecology import EdgeEcology
from strategies.relative_value_lab.metatron_ml_challenger import MetatronMLChallenger

HORIZONS=(15,30,60,120)
SELECTORS=("FLOW_EXHAUSTION","FLOW_PERSISTENT","EXHAUSTION_LIQUID","EXHAUSTION_TREND_GUARD","EXHAUSTION_ML_GUARD","FULL_EDGE_ECOLOGY")

def _mid(book):
    bids=book.get("bids") or []; asks=book.get("asks") or []
    return (float(bids[0][0])+float(asks[0][0]))/2 if bids and asks else 0.0
def _depth(book,side): return sum(float(p)*float(q) for p,q,*_ in (book.get(side) or []))
def _digest(s): return hashlib.sha256(s.encode()).hexdigest()
def _stats(vals):
    vals=list(vals); eq=peak=dd=0.; wins=sum(v>0 for v in vals)
    for v in vals: eq+=v; peak=max(peak,eq); dd=max(dd,peak-eq)
    return {"n":len(vals),"net_bps":round(sum(vals),4),"mean_bps":round(statistics.fmean(vals),4) if vals else 0.,
            "median_bps":round(statistics.median(vals),4) if vals else 0.,"win_rate":round(wins/len(vals),4) if vals else 0.,
            "max_drawdown_bps":round(dd,4)}
def _matched(rows,n,key):
    ranked=sorted(rows,key=lambda r:_digest(f"2306|{key}|{r['forecast_ts']}|{r['symbol']}"))
    return {r["observation_id"] for r in ranked[:n]}
def _books(settled,cost):
    out={}
    for h in HORIZONS:
        rows=[r for r in settled if r["horizon_sec"]==h and r.get("source_flow_sign",0)!=0]
        for mode in ("REVERSION","CONTINUATION"):
            field="reversion_bps" if mode=="REVERSION" else "continuation_bps"
            out[f"CONTROL_ALL_{mode}_H{h}"]=_stats(r[field]-cost for r in rows)
            for sel in SELECTORS:
                chosen=[r for r in rows if r["selectors"].get(sel)]
                out[f"{sel}_{mode}_H{h}"]=_stats(r[field]-cost for r in chosen)
                ids=_matched(rows,len(chosen),f"{sel}|{mode}|{h}")
                out[f"RANDOM_MATCHED_{sel}_{mode}_H{h}"]=_stats(r[field]-cost for r in rows if r["observation_id"] in ids)
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--symbol",default="BTC/USD")
    ap.add_argument("--duration-sec",type=int,default=3600); ap.add_argument("--interval-sec",type=float,default=5.)
    ap.add_argument("--cost-bps",type=float,default=0.); ap.add_argument("--output",type=Path,default=ROOT/"data/edge_ecology_v2.json")
    a=ap.parse_args(); client=KrakenPublicRestClient(); client.load_markets(); eco=EdgeEcology()
    hist=deque(maxlen=240); training=[]; ml=None; pending=[]; settled=[]; observations=[]
    prev_flow=0.; prev_bd=prev_ad=None; start=time.monotonic(); cycle=0
    while time.monotonic()-start<a.duration_sec:
        tick=time.monotonic(); cycle+=1; ts=int(time.time()*1000)
        book=client.fetch_order_book(a.symbol,limit=25); px=_mid(book); trades=client.fetch_trades(a.symbol,limit=200)
        cutoff=ts-int(max(10,a.interval_sec*3)*1000); recent=[x for x in trades if int(x.get("timestamp") or 0)>=cutoff]
        buy=sum(float(x.get("amount") or 0) for x in recent if x.get("side")=="buy")
        sell=sum(float(x.get("amount") or 0) for x in recent if x.get("side")=="sell")
        bd,ad=_depth(book,"bids"),_depth(book,"asks"); bids=book.get("bids") or []; asks=book.get("asks") or []
        spread=((float(asks[0][0])-float(bids[0][0]))/px*10000) if px and bids and asks else 0.
        hist.append(px); rets=[hist[i]/hist[i-1]-1 for i in range(1,len(hist)) if hist[i-1]]
        fv=eco.flow_voice(taker_buy_volume=buy,taker_sell_volume=sell,previous_imbalance=prev_flow)
        lv=eco.liquidity_voice(bid_depth=bd,ask_depth=ad,spread_bps=spread,previous_bid_depth=prev_bd,previous_ask_depth=prev_ad)
        tv=eco.trend_voice(returns=rets[-12:]); vv=eco.volatility_voice(returns=rets[-30:],baseline_vol=statistics.pstdev(rets) if len(rets)>2 else None)
        feature=[fv.score,lv.score,tv.score,vv.score,spread/10.]; training.append(feature)
        if ml is None and len(training)>=40: ml=MetatronMLChallenger(seed=2306); ml.fit(training[:40])
        challenge=ml.challenge(feature) if ml else None
        exhaustion=fv.state=="AGGRESSIVE_FLOW_EXHAUSTING"; persistent=fv.state=="DIRECTIONAL_FLOW_PERSISTENT"
        liquid=lv.state!="LIQUIDITY_FRAGILE"; trend_guard=tv.state!="TREND_PERSISTENT"; ml_guard=challenge is None or challenge.regime!="NOVEL_STATE"
        selectors={"FLOW_EXHAUSTION":exhaustion,"FLOW_PERSISTENT":persistent,"EXHAUSTION_LIQUID":exhaustion and liquid,
          "EXHAUSTION_TREND_GUARD":exhaustion and trend_guard,"EXHAUSTION_ML_GUARD":exhaustion and ml_guard,
          "FULL_EDGE_ECOLOGY":exhaustion and liquid and trend_guard and ml_guard}
        flow_sign=1 if prev_flow>0 else -1 if prev_flow<0 else 0; oid=_digest(f"{a.symbol}|{ts}")[:24]
        row={"observation_id":oid,"forecast_ts":ts,"symbol":a.symbol,"px":px,"source_flow":prev_flow,"source_flow_sign":flow_sign,"selectors":selectors,
          "states":{"flow":fv.state,"liquidity":lv.state,"trend":tv.state,"volatility":vv.state,"ml":challenge.regime if challenge else "WARMUP"},
          "scores":{"flow":fv.score,"liquidity":lv.score,"trend":tv.score,"volatility":vv.score,"spread_bps":spread},
          "authority":"research_only","execution_eligible":False}
        observations.append(row)
        if px:
            for h in HORIZONS: pending.append({**row,"due":ts+h*1000,"horizon_sec":h})
        still=[]
        for p in pending:
            if ts<p["due"]: still.append(p); continue
            raw=((px/p["px"])-1)*10000; cont=p["direction"]*raw
            settled.append({**p,"settled_ts":ts,"settled_px":px,"continuation_bps":cont,"reversion_bps":-cont})
        pending=still; prev_flow=fv.features["imbalance"]; prev_bd,prev_ad=bd,ad
        books=_books(settled,a.cost_bps)
        key="FULL_EDGE_ECOLOGY_FLOW_REVERSION_H30"; b=books.get(key,{})
        effects={"liquidity_veto":sum(x["selectors"]["FLOW_EXHAUSTION"] and not x["selectors"]["EXHAUSTION_LIQUID"] for x in observations),
          "trend_veto":sum(x["selectors"]["FLOW_EXHAUSTION"] and not x["selectors"]["EXHAUSTION_TREND_GUARD"] for x in observations),
          "ml_veto":sum(x["selectors"]["FLOW_EXHAUSTION"] and not x["selectors"]["EXHAUSTION_ML_GUARD"] for x in observations)}
        payload={"schema":"hivenance_edge_ecology_experiment_v2_1","protocol":"frozen_multi_horizon_directional_ecology",
          "symbol":a.symbol,"horizons_sec":HORIZONS,"cost_bps":a.cost_bps,"observation_count":len(observations),
          "settled_count":len(settled),"organ_marginal_effects":effects,"books":books,"observations":observations,"settled":settled,
          "private_orders":0,"execution_eligible":False,"promotion_eligible":False}
        a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(payload,indent=2))
        print(f"EDGE_V2 cycle={cycle} obs={len(observations)} settled={len(settled)} flow={fv.state} liq={lv.state} trend={tv.state} ml={row['states']['ml']} H30_full_n={b.get('n',0)} H30_full_net={b.get('net_bps',0):+.3f} veto[L/T/M]={effects['liquidity_veto']}/{effects['trend_veto']}/{effects['ml_veto']} orders=0",flush=True)
        time.sleep(max(.1,a.interval_sec-(time.monotonic()-tick)))
    return 0
if __name__=="__main__": raise SystemExit(main())
