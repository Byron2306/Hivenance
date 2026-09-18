#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> int:
    p=argparse.ArgumentParser(description="Report Hivenance Horizon micro/meso/macro context")
    p.add_argument("--database",default="data/hivenance_horizon_context.db")
    args=p.parse_args()
    path=Path(args.database)
    if not path.exists():
        print(f"No horizon database yet: {path}")
        return 0

    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    try:
        run=conn.execute(
            "SELECT * FROM horizon_runs ORDER BY started_ts DESC LIMIT 1"
        ).fetchone()
        print("Hivenance Horizon // long-player context")
        if run:
            print(
                f"collector_status={run['status']} interval={float(run['interval_sec']):.1f}s "
                f"authority={run['authority']}"
            )

        rows=conn.execute(
            """
            SELECT c.*
            FROM horizon_context c
            JOIN (
              SELECT symbol,MAX(ts) AS max_ts FROM horizon_context GROUP BY symbol
            ) x ON x.symbol=c.symbol AND x.max_ts=c.ts
            ORDER BY COALESCE(c.relative_strength_5m_bps,-1e18) DESC
            """
        ).fetchall()
        if not rows:
            print("No horizon context yet.")
            return 0

        print()
        print("Latest asset context")
        print("--------------------")
        for row in rows:
            try:
                ready=json.loads(row["readiness_json"] or "{}")
            except Exception:
                ready={}
            rel5=row["relative_strength_5m_bps"]
            rel15=row["relative_strength_15m_bps"]
            print(
                f"{str(row['symbol']):10s} "
                f"micro={str(row['micro_bias']):7s} "
                f"meso={str(row['meso_bias']):7s} "
                f"macro={str(row['macro_bias']):7s} "
                f"align={str(row['alignment']):12s} "
                f"regime={str(row['regime_hint']):13s} "
                f"5m_rel={'n/a' if rel5 is None else f'{float(rel5):+.2f}bps':>10s} "
                f"15m_rel={'n/a' if rel15 is None else f'{float(rel15):+.2f}bps':>10s} "
                f"warm15m={int(bool(ready.get('macro_15m')))} "
                f"warm1h={int(bool(ready.get('macro_1h')))}"
            )

        market=conn.execute(
            "SELECT * FROM horizon_market_context ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if market:
            print()
            print("Market-wide horizon state")
            print("-------------------------")
            print(
                f"median_spread={float(market['median_spread_bps'] or 0):.2f}bps "
                f"24h_positive_breadth={float(market['breadth_24h_positive'] or 0)*100:.1f}%"
            )
            print(
                f"aligned_up={int(market['aligned_up'] or 0)} "
                f"aligned_down={int(market['aligned_down'] or 0)} "
                f"conflict={int(market['conflict'] or 0)} "
                f"neutral={int(market['neutral'] or 0)}"
            )
            print(
                f"meso_relative_leader={market['meso_leader']} "
                f"macro_24h_leader={market['macro_leader']}"
            )

        coverage=conn.execute(
            """
            SELECT symbol,
                   (MAX(ts)-MIN(ts))/60.0 AS minutes,
                   COUNT(*) AS samples
            FROM horizon_ticks
            GROUP BY symbol
            ORDER BY symbol
            """
        ).fetchall()
        print()
        print("Accumulated local history")
        print("-------------------------")
        for row in coverage:
            print(
                f"{str(row['symbol']):10s} samples={int(row['samples']):5d} "
                f"coverage={float(row['minutes'] or 0):7.1f} min"
            )

        print()
        print("PRIVATE ORDERS: 0")
        return 0
    finally:
        conn.close()


if __name__=="__main__":
    raise SystemExit(main())
