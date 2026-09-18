#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare recent Phase-2 federated research quality")
    parser.add_argument("--database", type=Path, default=Path("data/swarm_data.db"))
    parser.add_argument("--window-hours", type=float, default=24.0)
    args = parser.parse_args()

    db_path = args.database
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cutoff_sql = f"(SELECT MAX(settled_ts) - {float(args.window_hours) * 3600.0} FROM hypothesis_outcomes)"

    print(f"Recent settlement window: last {args.window_hours:g} hours")
    print("")
    for row in cur.execute(
        f"""
        SELECT f.model_id,
               COUNT(*) AS settled_trades,
               ROUND(AVG(o.net_return_bps), 4) AS mean_net_bps,
               ROUND(AVG(o.positive_net), 4) AS win_rate,
               ROUND(SUM(o.net_return_bps), 2) AS cumulative_net_bps
        FROM hypothesis_forecasts f
        JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
        WHERE f.abstain=0
          AND o.settled_ts >= {cutoff_sql}
          AND (
            f.model_id LIKE 'candidate_%'
            OR f.model_id LIKE 'baseline_%'
            OR f.model_id LIKE 'breakout_%'
            OR f.model_id LIKE 'exhaustion_%'
          )
        GROUP BY f.model_id
        ORDER BY mean_net_bps DESC
        """
    ):
        print("|".join("" if value is None else str(value) for value in row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
