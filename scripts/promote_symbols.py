#!/usr/bin/env python3
"""Retired legacy promotion command.

This compatibility utility may summarize paper evidence, but it cannot promote a
symbol to tiny-live or normal. Phoenix Phases 2 through 5 own research readiness;
Phase 6 owns live order authority; Phase 7 owns scaling authority.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict


def load_memory(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    return {}


def summarize(db_path: str, memory_path: str, min_trades: int, min_win_rate: float, max_drawdown: float) -> dict:
    memory = load_memory(memory_path)
    stats = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT symbol, side, quantity, price FROM trades ORDER BY timestamp ASC").fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            conn.close()
        inventory = defaultdict(lambda: {"qty": 0.0, "cost": 0.0})
        for row in rows:
            symbol = str(row["symbol"] or "").upper()
            if not symbol:
                continue
            base = symbol.split("/")[0]
            side = str(row["side"] or "").upper()
            qty = float(row["quantity"] or 0)
            price = float(row["price"] or 0)
            if qty <= 0 or price <= 0:
                continue
            stats[base]["trades"] += 1
            inv = inventory[base]
            if side == "BUY":
                inv["cost"] += qty * price
                inv["qty"] += qty
            elif side == "SELL" and inv["qty"] > 0:
                avg = inv["cost"] / inv["qty"] if inv["qty"] else price
                pnl = (price - avg) * min(qty, inv["qty"])
                stats[base]["pnl"] += pnl
                stats[base]["wins" if pnl > 0 else "losses"] += 1
                inv["qty"] = max(0.0, inv["qty"] - qty)
                inv["cost"] = max(0.0, inv["cost"] - avg * qty)

    report = {}
    for base, row in stats.items():
        sells = row["wins"] + row["losses"]
        win_rate = row["wins"] / sells if sells else 0.0
        current = memory.get(base) or {}
        candidate = (
            row["trades"] >= min_trades
            and win_rate >= min_win_rate
            and float(current.get("max_drawdown_pct") or 0.0) <= max_drawdown
            and row["pnl"] > 0
        )
        report[base] = {
            "stage": "paper",
            "phoenix_candidate_ready": candidate,
            "next_required_phase": 2,
            "execution_authority": "none",
            "promotion_authority": "none",
            "trades": row["trades"],
            "wins": row["wins"],
            "losses": row["losses"],
            "win_rate": round(win_rate, 6),
            "pnl_est": round(row["pnl"], 8),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize legacy paper evidence without promotion authority")
    parser.add_argument("--db", default="data/swarm_data.db")
    parser.add_argument("--memory", default="data/symbol_memory.json")
    parser.add_argument("--min-trades", type=int, default=25)
    parser.add_argument("--min-win-rate", type=float, default=0.52)
    parser.add_argument("--max-drawdown", type=float, default=5.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = summarize(args.db, args.memory, args.min_trades, args.min_win_rate, args.max_drawdown)
    payload = {"legacy_promotion_retired": True, "records": report}
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
