#!/usr/bin/env python3
"""Run the live Kraken Futures perpetual public observer for Engine A.

Public CCXT market-data endpoints only (ticker, order book, funding rate).
No API keys, no authenticated endpoints, no order submission anywhere in
this process. Persists snapshots to the same ``observation_snapshots``
table Phase 1 uses, tagged ``venue=kraken_futures`` so
``derivatives_trend_lab.py`` prefers this genuine feed over the spot proxy
once enough history accumulates.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sqlite3

from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.derivatives_observer import (
    build_public_krakenfutures_client,
    run_derivatives_observer_once,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Kraken Futures public observer (Engine A price feed)")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--venue", default="kraken_futures")
    parser.add_argument("--interval-sec", type=int, default=300)
    parser.add_argument("--once", action="store_true", help="Collect one cycle and exit")
    parser.add_argument("--json", action="store_true", help="Print the complete cycle payload")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    client = build_public_krakenfutures_client()
    conn = sqlite3.connect(str(db_path))

    def collect() -> None:
        payload = run_derivatives_observer_once(client, conn, cfg, venue=args.venue)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            print(
                f"{'OK' if not payload.get('errors') else 'PARTIAL'} run={payload.get('run_id')} "
                f"observed={payload.get('symbols_successful', 0)}/{payload.get('symbols_attempted', 0)} "
                f"venue={payload.get('venue')} orders=0"
            )
            for error in payload.get("errors") or []:
                print(f"  error: {error}", file=sys.stderr)

    if args.once:
        collect()
        return 0

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    interval = max(30, int(args.interval_sec))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"Observation cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
