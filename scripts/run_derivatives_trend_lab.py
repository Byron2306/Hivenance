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
from strategies.volatility_breakout.derivatives_trend_lab import run_derivatives_trend_lab


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hivenance derivatives (perpetual futures) medium-horizon trend research lab "
            "(Engine A). Research-only: no live Kraken Futures market-data feed exists yet, "
            "so price/momentum are computed from the existing spot observation_snapshots "
            "table as an explicitly labeled proxy (see price_data_source in every receipt)."
        )
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--venue", default="kraken_futures")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--lookback-limit", type=int, default=100_000)
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    venue = str(args.venue or "kraken_futures").lower()
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    try:
        summary = run_derivatives_trend_lab(
            conn,
            cfg,
            venue=venue,
            lookback_limit=max(1000, int(args.lookback_limit or 100_000)),
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        return 0

    print(
        f"DERIVATIVES_TREND run={summary.get('run_id')} "
        f"receipts={summary.get('receipt_count', 0)} "
        f"accepted={summary.get('accepted_slice_count', 0)} "
        f"fee_verified={summary.get('fee_verified')} "
        f"price_data_source={summary.get('price_data_source')} "
        f"orders=0"
    )
    for row in (summary.get("best_slices") or [])[:5]:
        print(
            f"  {row.get('symbol')} dir={row.get('direction')} h={row.get('horizon_seconds')} "
            f"lookback={row.get('lookback_seconds')} policy={row.get('policy')} "
            f"n={row.get('entries')} mean_net={row.get('mean_net_bps')} "
            f"p25_holdout_net={row.get('lower_bound_net_bps')} "
            f"stressed={row.get('stressed_mean_net_bps')} "
            f"accepted={row.get('accepted')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
