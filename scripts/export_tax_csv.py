#!/usr/bin/env python3
"""Export Hivenance trades/fills to a SARS-friendly CSV starter file."""

import argparse
import csv
import os
import sqlite3
from datetime import datetime, timezone


def iso_from_ts(value):
    try:
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return str(value or "")


def export(db_path, out_path):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = []
    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(o.symbol, t.symbol, '') AS symbol,
                COALESCE(o.side, t.side, '') AS side,
                COALESCE(f.filled_qty, t.quantity, 0) AS quantity,
                COALESCE(f.avg_price, t.price, 0) AS price,
                COALESCE(f.fee, 0) AS fee,
                COALESCE(f.slippage_pct, 0) AS slippage_pct,
                COALESCE(o.venue, '') AS venue,
                COALESCE(o.order_id, f.order_id, '') AS order_id,
                COALESCE(f.client_order_id, o.client_order_id, '') AS client_order_id,
                COALESCE(f.ts, o.final_ts, o.placed_ts, t.timestamp) AS ts
            FROM trades t
            LEFT JOIN orders o ON o.symbol = t.symbol AND o.side = t.side
            LEFT JOIN fills f ON f.order_id = o.order_id OR f.client_order_id = o.client_order_id
            ORDER BY ts ASC
            """
        ).fetchall()
    except sqlite3.Error:
        rows = conn.execute(
            "SELECT timestamp AS ts, symbol, side, quantity, price, status FROM trades ORDER BY timestamp ASC"
        ).fetchall()

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "datetime_utc",
                "symbol",
                "side",
                "quantity",
                "price_usd",
                "gross_value_usd",
                "fee_usd",
                "slippage_pct",
                "venue",
                "order_id",
                "client_order_id",
                "notes",
            ],
        )
        writer.writeheader()
        for row in rows:
            d = dict(row)
            qty = float(d.get("quantity") or 0)
            price = float(d.get("price") or 0)
            writer.writerow({
                "datetime_utc": iso_from_ts(d.get("ts")),
                "symbol": d.get("symbol") or "",
                "side": (d.get("side") or "").upper(),
                "quantity": qty,
                "price_usd": price,
                "gross_value_usd": round(qty * price, 8),
                "fee_usd": d.get("fee") or 0,
                "slippage_pct": d.get("slippage_pct") or 0,
                "venue": d.get("venue") or "",
                "order_id": d.get("order_id") or "",
                "client_order_id": d.get("client_order_id") or "",
                "notes": "Review cost basis and FX/ZAR conversion before filing.",
            })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/swarm_data.db")
    parser.add_argument("--out", default="data/tax_export.csv")
    args = parser.parse_args()
    export(args.db, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
