#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> int:
    p=argparse.ArgumentParser(description="Report latest Phoenix relative-value pair-lab run")
    p.add_argument("--database",default="data/relative_value_pair_lab.db")
    args=p.parse_args()
    path=Path(args.database)
    if not path.exists():
        print(f"No pair-lab database yet: {path}")
        return 0

    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    try:
        run=conn.execute(
            "SELECT * FROM pair_lab_runs ORDER BY created_ts DESC LIMIT 1"
        ).fetchone()
        if not run:
            print("No pair-lab run found.")
            return 0
        rid=str(run["run_id"])
        rows=conn.execute(
            """
            SELECT * FROM pair_relationships
            WHERE run_id=?
            ORDER BY eligible DESC,stability_score DESC
            """,(rid,)
        ).fetchall()

        print(f"Phoenix Pair Laboratory // {rid}")
        print(
            f"symbols={int(run['symbol_count'])} pairs={int(run['pair_count'])} "
            f"eligible={int(run['eligible_pair_count'])}"
        )
        print()
        for row in rows:
            reasons=json.loads(row["rejection_reasons_json"] or "[]")
            status="ELIGIBLE" if int(row["eligible"] or 0) else "REFUSE"
            half="n/a" if row["half_life_seconds"] is None else f"{float(row['half_life_seconds']):.1f}s"
            z="n/a" if row["spread_zscore"] is None else f"{float(row['spread_zscore']):+.2f}z"
            print(
                f"{str(row['pair_id']):24s} {status:8s} "
                f"stability={float(row['stability_score'] or 0):.3f} "
                f"half={half:>8s} spread={z:>8s} "
                f"break={str(row['structural_break_state']):12s} "
                f"direct={int(row['direct_route_available'] or 0)} "
                f"reasons={','.join(reasons[:3]) if reasons else '-'}"
            )
        print()
        print("AUTHORITY: research evidence only")
        print("PRIVATE ORDERS: 0")
        return 0
    finally:
        conn.close()


if __name__=="__main__":
    raise SystemExit(main())
