#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx <= 0 or sy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def latest_run(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM live_streak_runs ORDER BY started_ts DESC LIMIT 1"
    ).fetchone()
    return str(row[0]) if row else None


def report(database: Path, run_id: str | None) -> int:
    if not database.exists():
        print(f"No database yet: {database}")
        return 0
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    run_id = run_id or latest_run(conn)
    if not run_id:
        print("No streak-lab run found.")
        return 0

    run = conn.execute(
        "SELECT * FROM live_streak_runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if not run:
        print(f"Run not found: {run_id}")
        return 1

    print(f"Phoenix Profit Streak Lab // {run_id}")
    print(f"status={run['status']} authority={run['authority']}")
    print()

    marks = conn.execute(
        """
        WITH latest AS (
            SELECT mutation_id, MAX(ts) AS ts
            FROM live_wallet_marks
            WHERE run_id=?
            GROUP BY mutation_id
        )
        SELECT w.*
        FROM live_wallet_marks w
        JOIN latest l
          ON w.mutation_id=l.mutation_id AND w.ts=l.ts
        WHERE w.run_id=?
        ORDER BY w.equity_usd DESC
        """,
        (run_id, run_id),
    ).fetchall()

    start_usd = 1000.0
    try:
        import json
        cfg = json.loads(run["config_json"] or "{}")
        start_usd = float(cfg.get("start_usd") or 1000.0)
    except Exception:
        pass

    action_counts = {
        str(row["mutation_id"]): int(row["n"])
        for row in conn.execute(
            """
            SELECT mutation_id, COUNT(*) AS n
            FROM live_paper_actions
            WHERE run_id=?
            GROUP BY mutation_id
            """,
            (run_id,),
        ).fetchall()
    }

    print("Mutation scorecard")
    print("------------------")
    for row in marks:
        mutation = str(row["mutation_id"])
        equity = float(row["equity_usd"])
        net = equity - start_usd
        print(
            f"{mutation:22s} equity={equity:10.4f} net={net:+9.4f} "
            f"cost={float(row['cumulative_cost_usd']):7.4f} "
            f"actions={action_counts.get(mutation, 0):4d} "
            f"open={int(row['open_positions'])}"
        )

    latencies = [
        float(row[0])
        for row in conn.execute(
            """
            SELECT DISTINCT cycle_latency_ms
            FROM live_wallet_marks
            WHERE run_id=? AND cycle_latency_ms IS NOT NULL
            """,
            (run_id,),
        ).fetchall()
    ]
    if latencies:
        print()
        print(
            "Cycle latency: "
            f"p50={percentile(latencies, 0.50):.1f}ms "
            f"p95={percentile(latencies, 0.95):.1f}ms "
            f"max={max(latencies):.1f}ms"
        )

    # Build worker vote vectors aligned by timestamp+symbol.
    rows = conn.execute(
        """
        SELECT ts, symbol, worker_id, vote
        FROM live_worker_votes
        WHERE run_id=? AND worker_ready=1
        ORDER BY ts, symbol, worker_id
        """,
        (run_id,),
    ).fetchall()
    frames: dict[tuple[float, str], dict[str, int]] = defaultdict(dict)
    workers: set[str] = set()
    for row in rows:
        key = (float(row["ts"]), str(row["symbol"]))
        worker = str(row["worker_id"])
        frames[key][worker] = int(row["vote"])
        workers.add(worker)

    workers = set(sorted(workers))
    correlations: list[tuple[float, str, str, int]] = []
    ws = sorted(workers)
    for i, left in enumerate(ws):
        for right in ws[i + 1:]:
            xs: list[float] = []
            ys: list[float] = []
            for frame in frames.values():
                if left in frame and right in frame:
                    xs.append(float(frame[left]))
                    ys.append(float(frame[right]))
            corr = pearson(xs, ys)
            if corr is not None:
                correlations.append((corr, left, right, len(xs)))

    if correlations:
        print()
        print("Strongest worker vote correlations")
        print("----------------------------------")
        for corr, left, right, n in sorted(
            correlations, key=lambda item: abs(item[0]), reverse=True
        )[:8]:
            print(f"{left:15s} {right:15s} r={corr:+.3f} n={n}")

    regimes = conn.execute(
        """
        SELECT inferred_regime, COUNT(*) AS n,
               AVG(regime_confidence) AS confidence
        FROM live_market_ticks
        WHERE run_id=?
        GROUP BY inferred_regime
        ORDER BY n DESC
        """,
        (run_id,),
    ).fetchall()
    if regimes:
        print()
        print("Observed inferred regimes")
        print("-------------------------")
        for row in regimes:
            print(
                f"{str(row['inferred_regime']):10s} "
                f"ticks={int(row['n']):5d} "
                f"mean_conf={float(row['confidence'] or 0):.3f}"
            )

    # Matched-random benchmark visibility.
    latest = {str(row["mutation_id"]): float(row["equity_usd"]) for row in marks}
    if "random30" in latest:
        random_net = latest["random30"] - start_usd
        print()
        print(f"Random-30 control net: {random_net:+.4f} USD")
        for candidate in ("majority5", "inferred_regime", "vol_breakout_pair"):
            if candidate in latest:
                candidate_net = latest[candidate] - start_usd
                print(
                    f"{candidate:22s} excess_vs_random30="
                    f"{candidate_net-random_net:+.4f} USD"
                )

    print()
    print("PRIVATE ORDERS: 0")
    conn.close()
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="data/live_profit_streak_lab.db")
    parser.add_argument("--run-id")
    parser.add_argument("--latest", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(report(Path(args.database), None if args.latest else args.run_id))
