#!/usr/bin/env python3
"""Backfill the canonical HiveNance Market Memory from public Kraken OHLCV.

Research-only. No credentials, private endpoints, orders, execution or promotion.
Kraken's public OHLC endpoint supplies a bounded recent window per timeframe, so
the script records exactly the history returned and never pretends it is complete.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from agents.kraken_public_rest import KrakenPublicRestClient
from agents.market_memory import MarketMemory, AUTHORITY

DEFAULT_SYMBOLS=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"]
DEFAULT_TF=["1m","5m","15m","1h","4h","1d","1w"]

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--symbols",nargs="+",default=DEFAULT_SYMBOLS)
    p.add_argument("--timeframes",nargs="+",default=DEFAULT_TF)
    p.add_argument("--database",default="data/hivenance_market_memory.db")
    p.add_argument("--limit",type=int,default=720)
    a=p.parse_args()
    client=KrakenPublicRestClient(); client.load_markets()
    memory=MarketMemory(a.database)
    summary={"schema":"hivenance_market_memory_backfill_v1","authority":AUTHORITY,
             "database":a.database,"symbols":{},"private_orders":0,
             "execution_eligible":False,"promotion_eligible":False}
    try:
        for symbol in a.symbols:
            summary["symbols"][symbol]={}
            for tf in a.timeframes:
                try:
                    rows=client.fetch_ohlcv(symbol,timeframe=tf,limit=a.limit)
                    for row in rows:
                        memory.append_bar(symbol=symbol,timeframe=tf,row=row)
                    first=int(rows[0][0]) if rows else None
                    last=int(rows[-1][0]) if rows else None
                    summary["symbols"][symbol][tf]={"bars":len(rows),"first_ts_ms":first,"last_ts_ms":last}
                    print(f"MEMORY {symbol:10s} {tf:3s} bars={len(rows):4d} first={first} last={last}",flush=True)
                    time.sleep(0.25)
                except Exception as exc:
                    summary["symbols"][symbol][tf]={"bars":0,"error":f"{type(exc).__name__}: {exc}"}
                    print(f"WARN {symbol} {tf}: {type(exc).__name__}: {exc}",flush=True)
        memory.append(source="market_memory_backfill",kind="BACKFILL_RECEIPT",
                      payload=summary,effective_ts_ms=int(time.time()*1000))
    finally:
        memory.close()
    out=ROOT/"data/hivenance_market_memory_backfill_summary.json"
    out.write_text(json.dumps(summary,indent=2))
    print(f"summary: {out}")
    print("PRIVATE ORDERS: 0")
    return 0

if __name__=="__main__": raise SystemExit(main())
