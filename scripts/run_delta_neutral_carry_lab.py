#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.delta_neutral_carry_lab import run_delta_neutral_carry_lab


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hivenance delta-neutral carry economics gate (Engine B): long spot / "
            "short perpetual, collect funding or basis income, stay approximately "
            "delta-neutral. This tool NEVER fabricates a funding-rate or basis feed -- "
            "no such live data source exists yet in this codebase. You must supply "
            "--funding-income-bps yourself (from manual research, an exchange API "
            "response you looked up, or a future live feed once one is built)."
        )
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--symbol", required=True, help="e.g. BTC/USD")
    parser.add_argument(
        "--funding-income-bps",
        type=float,
        required=True,
        help="Expected funding/basis income over --holding-period-hours, in bps. Manual input.",
    )
    parser.add_argument("--holding-period-hours", type=float, default=8.0)
    parser.add_argument("--required-net-return-bps", type=float, default=None)
    parser.add_argument(
        "--funding-income-source",
        default="manual_input_no_live_feed",
        help="Provenance tag for the funding-income figure supplied above.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        payload = run_delta_neutral_carry_lab(
            conn,
            cfg,
            symbol=str(args.symbol),
            funding_income_bps=float(args.funding_income_bps),
            required_net_return_bps=args.required_net_return_bps,
            holding_period_hours=float(args.holding_period_hours),
            funding_income_source=str(args.funding_income_source),
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0

    print(
        f"DELTA_NEUTRAL_CARRY receipt={payload['receipt_id']} symbol={payload['symbol']} "
        f"net_edge_bps={payload['net_edge_bps']} required_net_return_bps={payload['required_net_return_bps']} "
        f"accepted={payload['accepted']} execution_authority={payload['execution_authority']} orders=0"
    )
    if payload["reasons"]:
        print("  reasons:", ", ".join(payload["reasons"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
