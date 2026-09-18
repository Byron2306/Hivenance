#!/usr/bin/env python3
"""Standalone, read-only DEX market watcher.

Polls DexMarginOracle for the curated on-chain token universe on a fixed
interval and persists snapshots into the existing market_bee_snapshots table
via DataStoreAgent, the same path agents/coordinator.py uses in production.

No wallet writes, no order placement, no live trading. Safe to run any time.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from main import load_config
from agents.data_store_agent import DataStoreAgent
from agents.dex_margin_oracle import DexMarginOracle

_stop = False


def _handle_sigterm(signum, frame):
    global _stop
    _stop = True


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuous read-only DEX oracle watcher")
    parser.add_argument("--database", default="data/swarm_data.db")
    parser.add_argument("--interval-sec", type=int, default=300)
    parser.add_argument("--top-n", type=int, default=6)
    parser.add_argument("--amount-usd", type=float, default=25.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    cfg = load_config()
    store = DataStoreAgent(db_path=args.database)
    oracle = DexMarginOracle(cfg)

    universe = [t["symbol"] for t in oracle.token_universe()]
    print(
        f"DEX_WATCHER start chain_id={oracle.chain_id} universe={universe} "
        f"oneinch_key_set={bool(oracle.api_key)} interval_sec={args.interval_sec}",
        flush=True,
    )

    cycle = 0
    while not _stop:
        cycle += 1
        t0 = time.time()
        try:
            snapshot = oracle.market_bee_snapshot(top_n=args.top_n, amount_usd=args.amount_usd)
            evt = {
                "buzz": {"type": "buzz.market.bee", "source": "DEX_WATCHER", "ts": int(time.time() * 1000)},
                "payload": snapshot,
            }
            store.handle_event(evt)
            allowed = [r["symbol"] for r in snapshot.get("all", []) if r.get("allowed")]
            top = snapshot.get("top") or []
            best = top[0] if top else {}
            print(
                f"DEX_WATCHER cycle={cycle} scanned={len(snapshot.get('all', []))} "
                f"allowed={allowed} best_symbol={best.get('symbol')} best_score={best.get('score')} "
                f"took_sec={round(time.time() - t0, 2)}",
                flush=True,
            )
        except Exception as e:
            print(f"DEX_WATCHER cycle={cycle} ERROR={e}", flush=True)

        if args.once:
            break
        for _ in range(max(1, args.interval_sec)):
            if _stop:
                break
            time.sleep(1)

    print("DEX_WATCHER stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
