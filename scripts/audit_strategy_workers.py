#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


FEDERATED_TO_WORKER = {
    "adapter_freqtrade_breakout_v1": ["WORKER-BREAKOUT", "WORKER-MOMENTUM", "WORKER-VOL-EXPANSION"],
    "adapter_jesse_trend_pullback_v1": ["WORKER-SUPERTREND", "WORKER-SMA"],
    "candidate_freqai_transparent_linear_v1": ["WORKER-META-LABEL", "WORKER-FREQAI"],
    "candidate_finrl_conservative_policy_proxy_v1": ["WORKER-FINRL-RISK-POLICY"],
    "candidate_webcrypto_market_context_proxy_v1": ["WORKER-WEBCRYPTO-CONTEXT"],
    "candidate_cex_multi_horizon_oracle_v1": ["WORKER-DEX-MARGIN-ORACLE", "WORKER-CEX-HORIZON-ORACLE"],
    "candidate_triune_polyphonic_synthesis_v1": ["WORKER-TRIUNE", "WORKER-SERAPH", "WORKER-SOPHIA", "WORKER-CCE"],
    "breakout_continuation_v1": ["WORKER-BREAKOUT", "WORKER-VOL-EXPANSION"],
    "exhaustion_mean_reversion_v1": ["WORKER-RSI", "WORKER-RSI2", "WORKER-BOLLINGER"],
}


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def build_audit(database: Path, *, recent_limit: int = 50000, activation_limit: int = 20000) -> dict[str, Any]:
    conn = sqlite3.connect(str(database))
    try:
        activation = rows(
            conn,
            """
            SELECT model_id,
                   COUNT(*) AS forecasts,
                   SUM(CASE WHEN abstain=0 THEN 1 ELSE 0 END) AS active,
                   ROUND(1.0 * SUM(CASE WHEN abstain=0 THEN 1 ELSE 0 END) / COUNT(*), 6) AS activation_rate
            FROM (
                SELECT model_id, abstain
                FROM hypothesis_forecasts
                ORDER BY rowid DESC
                LIMIT ?
            )
            GROUP BY model_id
            ORDER BY active DESC, forecasts DESC
            """,
            (int(activation_limit),),
        )
        by_model = rows(
            conn,
            """
            WITH recent AS (
                SELECT forecast_id, net_return_bps, positive_net
                FROM hypothesis_outcomes
                ORDER BY rowid DESC
                LIMIT ?
            )
            SELECT f.model_id,
                   COUNT(*) AS settled,
                   SUM(o.positive_net) AS wins,
                   ROUND(1.0 * SUM(o.positive_net) / COUNT(*), 6) AS win_rate,
                   ROUND(AVG(o.net_return_bps), 6) AS mean_net_bps,
                   ROUND(SUM(o.net_return_bps), 6) AS total_net_bps
            FROM recent o
            JOIN hypothesis_forecasts f INDEXED BY sqlite_autoindex_hypothesis_forecasts_1
              ON f.forecast_id=o.forecast_id
            WHERE f.abstain=0
            GROUP BY f.model_id
            HAVING COUNT(*)>=3
            ORDER BY mean_net_bps DESC
            """,
            (int(recent_limit),),
        )
        by_slice = rows(
            conn,
            """
            WITH recent AS (
                SELECT forecast_id, net_return_bps, positive_net
                FROM hypothesis_outcomes
                ORDER BY rowid DESC
                LIMIT ?
            )
            SELECT f.model_id, f.hypothesis, f.horizon_seconds, f.direction,
                   COUNT(*) AS settled,
                   SUM(o.positive_net) AS wins,
                   ROUND(1.0 * SUM(o.positive_net) / COUNT(*), 6) AS win_rate,
                   ROUND(AVG(o.net_return_bps), 6) AS mean_net_bps,
                   ROUND(SUM(o.net_return_bps), 6) AS total_net_bps
            FROM recent o
            JOIN hypothesis_forecasts f INDEXED BY sqlite_autoindex_hypothesis_forecasts_1
              ON f.forecast_id=o.forecast_id
            WHERE f.abstain=0
            GROUP BY f.model_id, f.hypothesis, f.horizon_seconds, f.direction
            HAVING COUNT(*)>=3
            ORDER BY mean_net_bps DESC, settled DESC
            LIMIT 40
            """,
            (int(recent_limit),),
        )
        mapped = []
        activation_map = {str(row.get("model_id")): row for row in activation}
        score_map = {str(row.get("model_id")): row for row in by_model}
        for model_id in sorted(set(activation_map) | set(score_map) | set(FEDERATED_TO_WORKER)):
            score = score_map.get(model_id, {})
            active = activation_map.get(model_id, {})
            mapped.append({
                "model_id": model_id,
                "worker_roles": FEDERATED_TO_WORKER.get(model_id, []),
                "forecasts_recent": int(active.get("forecasts") or 0),
                "active_recent": int(active.get("active") or 0),
                "activation_rate": float(active.get("activation_rate") or 0.0),
                "settled_recent": int(score.get("settled") or 0),
                "win_rate": score.get("win_rate"),
                "mean_net_bps": score.get("mean_net_bps"),
                "total_net_bps": score.get("total_net_bps"),
            })
        positive_slices = [
            row for row in by_slice
            if float(row.get("mean_net_bps") or 0.0) > 0.0 and int(row.get("settled") or 0) >= 3
        ]
        return {
            "schema": "hivenance_strategy_worker_audit_v1",
            "generated_ts": time.time(),
            "database": str(database),
            "recent_outcome_limit": int(recent_limit),
            "activation_limit": int(activation_limit),
            "mapped_workers": mapped,
            "model_scorecard": by_model,
            "top_slices": by_slice,
            "positive_slices": positive_slices,
            "interpretation": {
                "legacy_workers_direct_phase2_authority": False,
                "legacy_workers_note": "WORKER-SMA/RSI/BREAKOUT/MOMENTUM/BOLLINGER/SUPERTREND are council-era signal workers; Phase-2 gates mostly consume native/federated research models.",
                "best_current_edge_candidate": positive_slices[0] if positive_slices else None,
            },
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
    parser = argparse.ArgumentParser(description="Audit whether strategy workers are contributing predictive edge.")
    parser.add_argument("--database", type=Path, default=Path("data/swarm_data.db"))
    parser.add_argument("--recent-limit", type=int, default=50000)
    parser.add_argument("--activation-limit", type=int, default=20000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    audit = build_audit(args.database, recent_limit=args.recent_limit, activation_limit=args.activation_limit)
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True, default=str))
        return 0
    print("STRATEGY WORKER AUDIT")
    print("legacy_workers_direct_phase2_authority=false")
    print_table(
        "MODEL SCORECARD",
        audit["model_scorecard"],
        ["model_id", "settled", "wins", "win_rate", "mean_net_bps", "total_net_bps"],
    )
    print_table(
        "TOP SLICES",
        audit["top_slices"][:15],
        ["model_id", "horizon_seconds", "direction", "settled", "wins", "win_rate", "mean_net_bps", "total_net_bps"],
    )
    print_table(
        "WORKER ROLE MAP",
        audit["mapped_workers"],
        ["model_id", "worker_roles", "forecasts_recent", "active_recent", "activation_rate", "settled_recent", "mean_net_bps"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
