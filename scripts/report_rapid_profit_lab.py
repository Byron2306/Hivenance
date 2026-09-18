#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from typing import Any


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def one(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    result = rows(conn, query, params)
    return result[0] if result else {}


def build_report(database: str) -> dict[str, Any]:
    now = time.time()
    conn = sqlite3.connect(database)
    try:
        status = rows(
            conn,
            """
            SELECT status, COUNT(*) AS n,
                   ROUND(SUM(COALESCE(net_return_bps, 0)), 2) AS total_net_bps,
                   ROUND(AVG(net_return_bps), 2) AS mean_net_bps
            FROM rapid_paper_tape_trades
            GROUP BY status
            ORDER BY status
            """,
        )
        pnl = one(
            conn,
            """
            SELECT COUNT(*) AS closed,
                   SUM(CASE WHEN net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN net_return_bps<=0 THEN 1 ELSE 0 END) AS losses,
                   ROUND(SUM(net_return_bps), 2) AS total_net_bps,
                   ROUND(AVG(net_return_bps), 2) AS mean_net_bps,
                   ROUND(MIN(net_return_bps), 2) AS worst_net_bps,
                   ROUND(MAX(net_return_bps), 2) AS best_net_bps
            FROM rapid_paper_tape_trades
            WHERE status IN ('CLOSED_WIN','CLOSED_LOSS')
            """,
        )
        closed = int(pnl.get("closed") or 0)
        wins = int(pnl.get("wins") or 0)
        pnl["win_rate"] = round(wins / closed, 4) if closed else 0.0
        open_summary = rows(
            conn,
            """
            SELECT symbol, model_id, direction, COUNT(*) AS open_trades,
                   MIN(datetime(target_ts, 'unixepoch')) AS next_target_utc,
                   ROUND(MIN(target_ts) - ?, 1) AS sec_until_next
            FROM rapid_paper_tape_trades
            WHERE status='OPEN'
            GROUP BY symbol, model_id, direction
            ORDER BY sec_until_next ASC, symbol ASC
            LIMIT 20
            """,
            (now,),
        )
        model_direction = rows(
            conn,
            """
            SELECT model_id, direction, COUNT(*) AS trades,
                   SUM(CASE WHEN net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   ROUND(1.0 * SUM(CASE WHEN net_return_bps>0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS win_rate,
                   ROUND(AVG(net_return_bps), 2) AS mean_net_bps,
                   ROUND(SUM(net_return_bps), 2) AS total_net_bps
            FROM rapid_paper_tape_trades
            WHERE status IN ('CLOSED_WIN','CLOSED_LOSS')
            GROUP BY model_id, direction
            ORDER BY total_net_bps ASC
            LIMIT 20
            """,
        )
        worst_scopes = rows(
            conn,
            """
            SELECT symbol, model_id, direction, COUNT(*) AS trades,
                   SUM(CASE WHEN net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   ROUND(AVG(net_return_bps), 2) AS mean_net_bps,
                   ROUND(SUM(net_return_bps), 2) AS total_net_bps
            FROM rapid_paper_tape_trades
            WHERE status IN ('CLOSED_WIN','CLOSED_LOSS')
            GROUP BY symbol, model_id, direction
            ORDER BY total_net_bps ASC
            LIMIT 12
            """,
        )
        champion_slices = rows(
            conn,
            """
            WITH recent_outcomes AS (
                SELECT *
                FROM hypothesis_outcomes
                ORDER BY settled_ts DESC
                LIMIT 10000
            )
            SELECT f.model_id, f.hypothesis, f.horizon_seconds, f.direction,
                   COUNT(*) AS samples,
                   SUM(CASE WHEN o.net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   ROUND(1.0 * SUM(CASE WHEN o.net_return_bps>0 THEN 1 ELSE 0 END) / COUNT(*), 4) AS win_rate,
                   ROUND(AVG(o.net_return_bps), 2) AS mean_net_bps,
                   ROUND(SUM(o.net_return_bps), 2) AS total_net_bps
            FROM recent_outcomes o
            JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
            WHERE f.abstain=0
            GROUP BY f.model_id, f.hypothesis, f.horizon_seconds, f.direction
            HAVING samples>=3
               AND win_rate>=0.5
               AND mean_net_bps>=5.0
               AND total_net_bps>=1.0
            ORDER BY mean_net_bps DESC, samples DESC
            LIMIT 15
            """,
        )
        crystals = rows(
            conn,
            """
            SELECT scope_key, COUNT(*) AS hits, ROUND(SUM(evidence_strength), 2) AS evidence_strength
            FROM crystal_registry
            WHERE crystal_family='negative_capability'
              AND phase_scope=2
              AND drift_status='active_refusal_memory'
            GROUP BY scope_key
            ORDER BY hits DESC, evidence_strength DESC
            LIMIT 12
            """,
        )
        latest = rows(
            conn,
            """
            SELECT status, symbol, model_id, direction,
                   ROUND(expected_net_bps, 2) AS expected_net_bps,
                   ROUND(net_return_bps, 2) AS net_return_bps,
                   datetime(updated_ts, 'unixepoch') AS updated_utc,
                   failure_reason
            FROM rapid_paper_tape_trades
            ORDER BY updated_ts DESC
            LIMIT 12
            """,
        )
        return {
            "schema": "rapid_profit_lab_report_v1",
            "authority": "paper_only_no_private_exchange",
            "database": database,
            "generated_ts": now,
            "status": status,
            "pnl": pnl,
            "open_summary": open_summary,
            "model_direction": model_direction,
            "worst_scopes": worst_scopes,
            "champion_scout_slices": champion_slices,
            "negative_refusal_memory": crystals,
            "latest_events": latest,
        }
    finally:
        conn.close()


def print_table(title: str, items: list[dict[str, Any]], columns: list[str]) -> None:
    print(title)
    if not items:
        print("  none")
        return
    widths = {column: max(len(column), *(len(str(item.get(column, ""))) for item in items)) for column in columns}
    print("  " + "  ".join(column.ljust(widths[column]) for column in columns))
    for item in items:
        print("  " + "  ".join(str(item.get(column, "")).ljust(widths[column]) for column in columns))


def main() -> int:
    parser = argparse.ArgumentParser(description="Report rapid paper profit-lab state.")
    parser.add_argument("--database", default="data/swarm_data.db")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report(args.database)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0
    pnl = report["pnl"]
    print("RAPID PROFIT LAB")
    print(f"authority={report['authority']} private_orders=0")
    print(
        f"closed={pnl.get('closed', 0)} wins={pnl.get('wins', 0)} losses={pnl.get('losses', 0)} "
        f"win_rate={float(pnl.get('win_rate', 0.0)):.2%} mean_net_bps={pnl.get('mean_net_bps')} "
        f"total_net_bps={pnl.get('total_net_bps')}"
    )
    print_table("STATUS", report["status"], ["status", "n", "total_net_bps", "mean_net_bps"])
    print_table("OPEN EXPOSURE", report["open_summary"], ["symbol", "model_id", "direction", "open_trades", "next_target_utc", "sec_until_next"])
    print_table("MODEL/DIRECTION", report["model_direction"], ["model_id", "direction", "trades", "wins", "win_rate", "mean_net_bps", "total_net_bps"])
    print_table("CHAMPION SCOUT SLICES", report["champion_scout_slices"], ["model_id", "hypothesis", "horizon_seconds", "direction", "samples", "wins", "win_rate", "mean_net_bps", "total_net_bps"])
    print_table("WORST SCOPES", report["worst_scopes"], ["symbol", "model_id", "direction", "trades", "wins", "mean_net_bps", "total_net_bps"])
    print_table("NEGATIVE MEMORY", report["negative_refusal_memory"], ["hits", "evidence_strength", "scope_key"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
