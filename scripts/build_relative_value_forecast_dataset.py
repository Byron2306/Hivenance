#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.relative_value_lab.dataset import RelativeValueDatasetBuilder


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build leakage-safe Phoenix relative-value forecast dataset")
    parser.add_argument("--database", type=Path, default=Path("data/relative_value_microstructure.db"))
    parser.add_argument("--run-id")
    parser.add_argument("--output", type=Path, default=Path("data/relative_value_forecast_dataset.jsonl"))
    parser.add_argument("--summary-output", type=Path, default=Path("data/relative_value_forecast_dataset_summary.json"))
    parser.add_argument("--relationship-window-samples", type=int, default=120)
    parser.add_argument("--minimum-relationship-samples", type=int, default=60)
    parser.add_argument("--horizons", nargs="+", type=int, default=[10, 30, 60, 120])
    parser.add_argument("--venue", default="kraken")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    if args.run_id:
        run_id = args.run_id
    else:
        row = conn.execute(
            "SELECT run_id FROM relative_value_microstructure_runs ORDER BY started_ts DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise SystemExit("No microstructure run found")
        run_id = str(row["run_id"])

    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT symbol, timestamp_ms, mid, spread_bps,
                   book_imbalance_25bps, quote_ofi_proxy,
                   aggressor_flow_imbalance, trade_count,
                   trade_intensity_per_sec, depth_recovery_score,
                   data_quality
            FROM relative_value_microstructure_snapshots
            WHERE run_id=?
            ORDER BY timestamp_ms, symbol
            """,
            (run_id,),
        )
    ]
    conn.close()

    builder = RelativeValueDatasetBuilder(
        relationship_window_samples=args.relationship_window_samples,
        minimum_relationship_samples=args.minimum_relationship_samples,
        horizons_seconds=args.horizons,
    )
    examples, summary = builder.build(rows, venue=args.venue)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example.to_dict(), sort_keys=True, ensure_ascii=True) + "\n")

    payload = {
        "schema": "hivenance_relative_value_dataset_summary_v1",
        "source_run_id": run_id,
        "source_database": str(args.database),
        "output": str(args.output),
        **summary.to_dict(),
        "execution_authority": "none",
        "orders_submitted": 0,
    }
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    print("Phoenix Relative-Value Forecast Dataset")
    print(f"source_run={run_id}")
    print(f"examples={summary.examples}")
    print(f"pairs_seen={summary.pairs_seen}")
    print(f"pairs_eligible={summary.pairs_eligible_at_least_once}")
    print(f"fully_labeled={summary.fully_labeled_examples}")
    print(f"output={args.output}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())