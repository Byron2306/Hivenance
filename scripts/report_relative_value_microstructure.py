#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report Phoenix relative-value microstructure evidence")
    parser.add_argument("--database", type=Path, default=Path("data/relative_value_microstructure.db"))
    parser.add_argument("--run-id")
    return parser.parse_args()


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def fmt(value: float | None, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:.4f}{suffix}"


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    if args.run_id:
        run = conn.execute(
            "SELECT * FROM relative_value_microstructure_runs WHERE run_id=?",
            (args.run_id,),
        ).fetchone()
    else:
        run = conn.execute(
            "SELECT * FROM relative_value_microstructure_runs ORDER BY started_ts DESC LIMIT 1"
        ).fetchone()
    if run is None:
        raise SystemExit("No microstructure run found")

    rows = conn.execute(
        """
        SELECT * FROM relative_value_microstructure_snapshots
        WHERE run_id=?
        ORDER BY timestamp_ms, symbol
        """,
        (run["run_id"],),
    ).fetchall()

    print(f"Phoenix Relative-Value Microstructure // {run['run_id']}")
    print(f"status={run['status']} authority={run['authority']}")
    print(f"snapshots={len(rows)} errors={run['error_count']}")
    missing = json.loads(run["missing_symbols_json"] or "[]")
    if missing:
        print("missing_symbols=" + ",".join(missing))
    print()
    print("Symbol evidence")
    print("---------------")
    symbols = sorted({row["symbol"] for row in rows})
    for symbol in symbols:
        subset = [row for row in rows if row["symbol"] == symbol]
        spreads = [float(row["spread_bps"]) for row in subset if row["spread_bps"] is not None]
        ofi = [float(row["quote_ofi_proxy"]) for row in subset if row["quote_ofi_proxy"] is not None]
        flow = [
            float(row["aggressor_flow_imbalance"])
            for row in subset
            if row["aggressor_flow_imbalance"] is not None
        ]
        quality = [float(row["data_quality"]) for row in subset]
        trades = sum(int(row["trade_count"]) for row in subset)
        print(
            f"{symbol:12s} n={len(subset):4d} "
            f"spread={fmt(mean(spreads),'bps'):>12s} "
            f"quote_ofi={fmt(mean(ofi)):>8s} "
            f"trade_flow={fmt(mean(flow)):>8s} "
            f"quality={fmt(mean(quality)):>8s} "
            f"trades={trades:6d}"
        )
    print()
    print("PRIVATE ORDERS: 0")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
