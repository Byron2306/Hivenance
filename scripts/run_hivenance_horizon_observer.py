#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import time
import urllib.error
import uuid
from collections import deque
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from agents.horizon_context import AUTHORITY, HorizonContextAgent
from scripts.run_live_profit_streak_swarm import KrakenPublicFeed

SCHEMA="hivenance_horizon_observer_v1"


def js(value:Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)


class HorizonObserver:
    def __init__(self,args:argparse.Namespace) -> None:
        self.args=args
        self.run_id=f"horizon-{uuid.uuid4().hex[:12]}"
        self.feed=KrakenPublicFeed(args.symbols)
        self.agent=HorizonContextAgent(deadband_bps=args.deadband_bps)
        self.history={symbol:deque(maxlen=args.max_history_samples) for symbol in args.symbols}
        self.conn=sqlite3.connect(args.database)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._schema()
        self._restore_history()

    def _schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS horizon_runs(
          run_id TEXT PRIMARY KEY,started_ts REAL,ended_ts REAL,status TEXT,
          schema TEXT,authority TEXT,interval_sec REAL,symbols_json TEXT);
        CREATE TABLE IF NOT EXISTS horizon_ticks(
          symbol TEXT,ts REAL,price REAL,bid REAL,ask REAL,spread_bps REAL,
          open_24h REAL,high_24h REAL,low_24h REAL,volume_24h REAL,
          source TEXT,
          PRIMARY KEY(symbol,ts));
        CREATE INDEX IF NOT EXISTS idx_horizon_ticks_symbol_ts
          ON horizon_ticks(symbol,ts DESC);
        CREATE TABLE IF NOT EXISTS horizon_context(
          symbol TEXT,ts REAL,micro_bias TEXT,meso_bias TEXT,macro_bias TEXT,
          micro_score_bps REAL,meso_score_bps REAL,return_24h_bps REAL,
          alignment TEXT,regime_hint TEXT,
          relative_strength_5m_bps REAL,relative_strength_15m_bps REAL,
          readiness_json TEXT,context_json TEXT,
          PRIMARY KEY(symbol,ts));
        CREATE INDEX IF NOT EXISTS idx_horizon_context_symbol_ts
          ON horizon_context(symbol,ts DESC);
        CREATE TABLE IF NOT EXISTS horizon_market_context(
          ts REAL PRIMARY KEY,median_spread_bps REAL,breadth_24h_positive REAL,
          aligned_up INTEGER,aligned_down INTEGER,conflict INTEGER,neutral INTEGER,
          meso_leader TEXT,macro_leader TEXT,context_json TEXT);
        """)
        self.conn.execute(
            "INSERT INTO horizon_runs VALUES (?,?,?,?,?,?,?,?)",
            (
                self.run_id,time.time(),None,"RUNNING",SCHEMA,AUTHORITY,
                float(self.args.interval_sec),js(self.args.symbols),
            ),
        )
        self.conn.commit()

    def _restore_history(self) -> None:
        cutoff=time.time()-float(self.args.restore_hours)*3600.0
        for symbol in self.args.symbols:
            rows=self.conn.execute(
                """
                SELECT ts,price FROM horizon_ticks
                WHERE symbol=? AND ts>=?
                ORDER BY ts ASC
                """,(symbol,cutoff)
            ).fetchall()
            for row in rows[-self.args.max_history_samples:]:
                self.history[symbol].append((float(row["ts"]),float(row["price"])))
            if rows:
                print(f"  restored {symbol}: {len(self.history[symbol])} samples")

    @staticmethod
    def _return_bps(history:deque,now:float,horizon:float) -> float | None:
        if not history:
            return None
        latest_ts,latest_price=history[-1]
        target=now-horizon
        prior=None
        for ts,price in reversed(history):
            if ts<=target:
                prior=(ts,price)
                break
        if prior is None or prior[1]<=0 or latest_price<=0:
            return None
        return (latest_price/prior[1]-1.0)*10000.0

    @staticmethod
    def _vol_bps(history:deque,now:float,horizon:float) -> float | None:
        values=[(ts,p) for ts,p in history if ts>=now-horizon and p>0]
        if len(values)<3:
            return None
        rets=[values[i][1]/values[i-1][1]-1.0 for i in range(1,len(values)) if values[i-1][1]>0]
        if len(rets)<2:
            return None
        return statistics.pstdev(rets)*10000.0

    def _returns(self,symbol:str,now:float) -> dict[str,float | None]:
        h=self.history[symbol]
        return {
            "10s":self._return_bps(h,now,10.0),
            "30s":self._return_bps(h,now,30.0),
            "2m":self._return_bps(h,now,120.0),
            "5m":self._return_bps(h,now,300.0),
            "15m":self._return_bps(h,now,900.0),
            "1h":self._return_bps(h,now,3600.0),
        }

    def _vols(self,symbol:str,now:float) -> dict[str,float | None]:
        h=self.history[symbol]
        return {
            "30s":self._vol_bps(h,now,30.0),
            "5m":self._vol_bps(h,now,300.0),
        }

    def cycle(self) -> None:
        started=time.perf_counter()
        prices,volumes,meta=self.feed.poll()
        now=time.time()
        contexts={}
        returns_by_symbol={}

        for symbol in self.args.symbols:
            price=float(prices.get(symbol) or self.feed.last_prices.get(symbol) or 0.0)
            if price<=0:
                continue
            self.history[symbol].append((now,price))
            returns_by_symbol[symbol]=self._returns(symbol,now)
            self.conn.execute(
                "INSERT OR REPLACE INTO horizon_ticks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    symbol,now,price,
                    float(self.feed.last_bid.get(symbol,0.0)),
                    float(self.feed.last_ask.get(symbol,0.0)),
                    float(self.feed.last_spread_bps.get(symbol,0.0)),
                    float(self.feed.last_24h_open.get(symbol,0.0)),
                    float(self.feed.last_24h_high.get(symbol,0.0)),
                    float(self.feed.last_24h_low.get(symbol,0.0)),
                    float(self.feed.last_24h_volume.get(symbol,0.0)),
                    "kraken_public_ticker",
                ),
            )

        cross={key:[] for key in ("30s","2m","5m","15m","1h")}
        for returns in returns_by_symbol.values():
            for key in cross:
                value=returns.get(key)
                if value is not None:
                    cross[key].append(float(value))

        for symbol,returns in returns_by_symbol.items():
            ticker={
                "last":float(self.feed.last_prices.get(symbol,0.0)),
                "open":float(self.feed.last_24h_open.get(symbol,0.0)),
                "high":float(self.feed.last_24h_high.get(symbol,0.0)),
                "low":float(self.feed.last_24h_low.get(symbol,0.0)),
                "volume":float(self.feed.last_24h_volume.get(symbol,0.0)),
            }
            context=self.agent.build(
                symbol=symbol,
                timestamp=now,
                returns_bps=returns,
                realized_vol_bps=self._vols(symbol,now),
                ticker_24h=ticker,
                cross_sectional_returns=cross,
            ).to_dict()
            contexts[symbol]=context
            self.conn.execute(
                "INSERT OR REPLACE INTO horizon_context VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    symbol,now,
                    context["micro"]["bias"],context["meso"]["bias"],context["macro"]["bias"],
                    float(context["micro"]["score_bps"] or 0.0),
                    float(context["meso"]["score_bps"] or 0.0),
                    float(context["macro"]["return_24h_bps"] or 0.0),
                    context["alignment"],context["regime_hint"],
                    context["relative_strength"].get("5m"),
                    context["relative_strength"].get("15m"),
                    js(context["readiness"]),js(context),
                ),
            )

        if contexts:
            spreads=[float(self.feed.last_spread_bps.get(s,0.0)) for s in contexts if self.feed.last_spread_bps.get(s) is not None]
            ret24=[float(c["macro"]["return_24h_bps"] or 0.0) for c in contexts.values()]
            counts={"ALIGNED_UP":0,"ALIGNED_DOWN":0,"CONFLICT":0,"NEUTRAL":0}
            for c in contexts.values():
                counts[c["alignment"]]=counts.get(c["alignment"],0)+1
            meso_leader=max(contexts.values(),key=lambda c:float(c["relative_strength"].get("5m") or -1e18))["symbol"]
            macro_leader=max(contexts.values(),key=lambda c:float(c["macro"]["return_24h_bps"] or -1e18))["symbol"]
            market_payload={
                "authority":AUTHORITY,
                "breadth_24h_positive":sum(v>0 for v in ret24)/max(1,len(ret24)),
                "median_return_24h_bps":statistics.median(ret24) if ret24 else 0.0,
                "alignment_counts":counts,
                "meso_leader":meso_leader,
                "macro_leader":macro_leader,
            }
            self.conn.execute(
                "INSERT OR REPLACE INTO horizon_market_context VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    now,statistics.median(spreads) if spreads else 0.0,
                    market_payload["breadth_24h_positive"],
                    counts.get("ALIGNED_UP",0),counts.get("ALIGNED_DOWN",0),
                    counts.get("CONFLICT",0),counts.get("NEUTRAL",0),
                    meso_leader,macro_leader,js(market_payload),
                ),
            )
        self.conn.commit()

        if self.args.verbose or int(now)%self.args.report_every_sec<max(1,int(self.args.interval_sec)):
            cycle_ms=(time.perf_counter()-started)*1000.0
            print(
                f"\n[{time.strftime('%H:%M:%S')}] horizon-observer cycle={cycle_ms:.0f}ms "
                f"pairs={len(contexts)} authority={AUTHORITY}"
            )
            for symbol,c in sorted(contexts.items()):
                ready=c["readiness"]
                print(
                    f"  {symbol:10s} micro={c['micro']['bias']:7s} "
                    f"meso={c['meso']['bias']:7s} macro={c['macro']['bias']:7s} "
                    f"align={c['alignment']:12s} regime={c['regime_hint']:13s} "
                    f"5m_rel={str(c['relative_strength'].get('5m')):>10s} "
                    f"warm=15m:{int(ready['macro_15m'])}/1h:{int(ready['macro_1h'])}"
                )

    def close(self,status:str) -> None:
        self.conn.execute(
            "UPDATE horizon_runs SET ended_ts=?,status=? WHERE run_id=?",
            (time.time(),status,self.run_id),
        )
        self.conn.commit()
        print(f"SQLite: {self.args.database}")
        print(f"run_id: {self.run_id}")
        print(f"AUTHORITY: {AUTHORITY}")
        print("PRIVATE ORDERS: 0")
        self.conn.close()

    def run(self) -> int:
        self.feed.seed_prices()
        print(
            f"Starting Hivenance Horizon observer at {self.args.interval_sec:.1f}s cadence. "
            "micro=10/30s meso=2/5m macro=15m/1h+24h ticker. No orders."
        )
        deadline=None if self.args.duration_sec==0 else time.monotonic()+self.args.duration_sec
        status="COMPLETE"
        try:
            while deadline is None or time.monotonic()<deadline:
                began=time.monotonic()
                try:
                    self.cycle()
                except (
                    urllib.error.URLError,urllib.error.HTTPError,TimeoutError,
                    RuntimeError,json.JSONDecodeError
                ) as exc:
                    print(f"WARN horizon cycle: {type(exc).__name__}: {exc}")
                time.sleep(max(0.0,self.args.interval_sec-(time.monotonic()-began)))
        except KeyboardInterrupt:
            status="INTERRUPTED"
        finally:
            self.close(status)
        return 0


def parse_args() -> argparse.Namespace:
    p=argparse.ArgumentParser(description="Long-running public-market micro/meso/macro Hivenance observer")
    p.add_argument("--symbols",nargs="+",default=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"])
    p.add_argument("--database",default="data/hivenance_horizon_context.db")
    p.add_argument("--duration-sec",type=int,default=0,help="0 means run until interrupted")
    p.add_argument("--interval-sec",type=float,default=5.0)
    p.add_argument("--restore-hours",type=float,default=2.0)
    p.add_argument("--max-history-samples",type=int,default=2000)
    p.add_argument("--deadband-bps",type=float,default=1.0)
    p.add_argument("--report-every-sec",type=int,default=30)
    p.add_argument("--verbose",action="store_true")
    args=p.parse_args()
    if args.interval_sec<2.0:
        p.error("--interval-sec must be >= 2.0 for the long-running observer")
    if args.duration_sec<0:
        p.error("--duration-sec must be >= 0")
    return args


if __name__=="__main__":
    raise SystemExit(HorizonObserver(parse_args()).run())
