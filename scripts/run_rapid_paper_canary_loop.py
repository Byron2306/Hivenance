#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.canary_lab import TinyLiveCanary
from strategies.volatility_breakout.canary_store import CanaryStore


def _compact_report(report: dict[str, Any], scorecard: dict[str, Any]) -> dict[str, Any]:
    intent = report.get("canary_intent") if isinstance(report.get("canary_intent"), dict) else {}
    settlement = report.get("settlement") if isinstance(report.get("settlement"), dict) else {}
    cap_reconciliation = (
        report.get("open_cap_reconciliation")
        if isinstance(report.get("open_cap_reconciliation"), dict)
        else {}
    )
    receipts = settlement.get("receipts") if isinstance(settlement.get("receipts"), list) else []
    return {
        "schema": "rapid_paper_canary_loop_report_v1",
        "status": report.get("status"),
        "state": report.get("state"),
        "settled": int(settlement.get("settled") or 0),
        "wins": int(settlement.get("wins") or 0),
        "losses": int(settlement.get("losses") or 0),
        "expired": int(settlement.get("expired") or 0),
        "pruned": int(cap_reconciliation.get("pruned") or 0),
        "opened_symbol": intent.get("symbol"),
        "opened_side": intent.get("side"),
        "source_trade_id": report.get("source_trade_id"),
        "recent_receipts": [
            {
                "symbol": receipt.get("symbol"),
                "side": receipt.get("side"),
                "gross_return_bps": receipt.get("gross_return_bps"),
                "net_return_bps": receipt.get("net_return_bps"),
                "status": receipt.get("status"),
                "source_trade_id": receipt.get("source_trade_id"),
            }
            for receipt in receipts[:5]
        ],
        "scorecard": {
            key: scorecard.get(key)
            for key in (
                "paper_canary_intents",
                "paper_canary_open",
                "paper_canary_settled",
                "paper_canary_wins",
                "paper_canary_losses",
                "paper_canary_expired",
                "paper_canary_pruned",
                "paper_canary_win_rate",
                "paper_canary_mean_net_bps",
                "live_orders_submitted",
            )
        },
        "authority": "paper_only_no_private_exchange",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuously run the Phase-6 rapid paper canary without loading private exchange credentials."
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path, default=ROOT / "config/high_vol_low_stakes.yaml")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--interval-sec", type=int, default=20)
    parser.add_argument("--duration-sec", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--backfill-first", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/swarm_data.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    store = DataStoreAgent(str(db_path))
    canary = TinyLiveCanary(cfg, store, None, live_interlock=False)
    phase6 = CanaryStore(store)

    if args.backfill_first:
        backfill = canary.backfill_rapid_canary_memory(limit=500)
        print(f"CANARY_BACKFILL examined={backfill.get('examined', 0)} persisted={backfill.get('persisted', 0)}", flush=True)

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    started = time.monotonic()
    cycle = 0
    try:
        while not stopping:
            cycle += 1
            try:
                report = canary.run_once(live_requested=False)
                compact = _compact_report(report, phase6.scorecard())
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                print(
                    f"CANARY_LOOP cycle={cycle} status=DB_BUSY retrying=true error=database_is_locked",
                    flush=True,
                )
                time.sleep(min(5.0, max(1.0, float(args.interval_sec or 20))))
                continue
            compact["cycle"] = cycle
            if args.json:
                print(json.dumps(compact, sort_keys=True, default=str), flush=True)
            else:
                print(
                    f"CANARY_LOOP cycle={cycle} status={compact['status']} "
                    f"settled={compact['settled']} wins={compact['wins']} losses={compact['losses']} "
                    f"expired={compact['expired']} pruned={compact['pruned']} "
                    f"open={compact['scorecard'].get('paper_canary_open')} "
                    f"win_rate={compact['scorecard'].get('paper_canary_win_rate')} "
                    f"mean_net={compact['scorecard'].get('paper_canary_mean_net_bps')} "
                    f"live_orders=0",
                    flush=True,
                )
                if compact.get("opened_symbol"):
                    print(
                        f"CANARY_OPENED {compact['opened_symbol']} {compact.get('opened_side')} "
                        f"source={compact.get('source_trade_id')}",
                        flush=True,
                    )
                for receipt in compact["recent_receipts"]:
                    print(
                        f"CANARY_SETTLED {receipt.get('symbol')} {receipt.get('side')} "
                        f"gross_bps={float(receipt.get('gross_return_bps') or 0.0):.2f} "
                        f"net_bps={float(receipt.get('net_return_bps') or 0.0):.2f} "
                        f"status={receipt.get('status')}",
                        flush=True,
                    )
            if int(args.duration_sec or 0) > 0 and time.monotonic() - started >= int(args.duration_sec):
                break
            deadline = time.monotonic() + max(1, int(args.interval_sec or 20))
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.5, deadline - time.monotonic()))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
