#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
from pathlib import Path
from typing import Any, Iterable

DEFAULTS = {
    "a": "data/live_profit_streak_lab.db",
    "b": "data/live_rotation_streak_lab.db",
    "c": "data/live_relative_drizzle_lab.db",
    "d": "data/live_inventory_drizzle_lab.db",
}


def mean(values: Iterable[float]) -> float:
    vals = [float(v) for v in values]
    return statistics.mean(vals) if vals else 0.0


def median(values: Iterable[float]) -> float:
    vals = [float(v) for v in values]
    return statistics.median(vals) if vals else 0.0


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * max(0.0, min(1.0, q))
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def exact_binomial_two_sided(k: int, n: int, p: float = 0.5) -> float | None:
    if n <= 0:
        return None
    k = max(0, min(int(k), int(n)))
    probs = [
        math.comb(n, i) * (p ** i) * ((1.0 - p) ** (n - i))
        for i in range(n + 1)
    ]
    observed = probs[k]
    return min(1.0, sum(prob for prob in probs if prob <= observed + 1e-15))


def moving_block_bootstrap_mean(
    values: list[float],
    *,
    block_length: int = 5,
    iterations: int = 4000,
    seed: int = 20260918,
) -> dict[str, Any]:
    vals = [float(v) for v in values]
    n = len(vals)
    if not vals:
        return {"n": 0, "mean": None, "median": None, "ci95": [None, None]}
    if n == 1:
        return {
            "n": 1,
            "mean": vals[0],
            "median": vals[0],
            "ci95": [vals[0], vals[0]],
        }
    block_length = max(1, min(int(block_length), n))
    starts = list(range(0, n - block_length + 1))
    rng = random.Random(seed)
    boot = []
    for _ in range(max(200, int(iterations))):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.choice(starts)
            sample.extend(vals[start : start + block_length])
        boot.append(statistics.mean(sample[:n]))
    return {
        "n": n,
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "ci95": [percentile(boot, 0.025), percentile(boot, 0.975)],
        "block_length": block_length,
        "iterations": len(boot),
    }


def bh_fdr(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usable = [
        (index, float(item["p_value"]))
        for index, item in enumerate(items)
        if item.get("p_value") is not None
    ]
    if not usable:
        return items
    usable.sort(key=lambda pair: pair[1])
    m = len(usable)
    adjusted = [1.0] * m
    running = 1.0
    for rank_index in range(m - 1, -1, -1):
        _, p = usable[rank_index]
        rank = rank_index + 1
        running = min(running, p * m / rank)
        adjusted[rank_index] = min(1.0, running)
    output = [dict(item) for item in items]
    for rank_index, (original_index, _) in enumerate(usable):
        output[original_index]["q_value_bh"] = adjusted[rank_index]
    return output


def connect(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def latest_run_id(conn: sqlite3.Connection, table: str) -> str | None:
    row = conn.execute(
        f"SELECT run_id FROM {table} ORDER BY started_ts DESC LIMIT 1"
    ).fetchone()
    return str(row["run_id"]) if row else None


def safe_config(row: sqlite3.Row | None) -> dict[str, Any]:
    if not row:
        return {}
    try:
        return json.loads(row["config_json"] or "{}")
    except Exception:
        return {}


def analyze_a(path: Path) -> dict[str, Any]:
    conn = connect(path)
    if conn is None:
        return {"available": False}
    try:
        rid = latest_run_id(conn, "live_streak_runs")
        if not rid:
            return {"available": False}
        run = conn.execute(
            "SELECT * FROM live_streak_runs WHERE run_id=?", (rid,)
        ).fetchone()
        cfg = safe_config(run)
        start = float(cfg.get("start_usd") or 1000.0)
        marks = conn.execute(
            """
            WITH latest AS (
              SELECT mutation_id,MAX(ts) AS ts
              FROM live_wallet_marks WHERE run_id=? GROUP BY mutation_id
            )
            SELECT w.* FROM live_wallet_marks w
            JOIN latest x ON x.mutation_id=w.mutation_id AND x.ts=w.ts
            WHERE w.run_id=?
            """,
            (rid, rid),
        ).fetchall()
        counts = {
            str(row["mutation_id"]): int(row["n"])
            for row in conn.execute(
                "SELECT mutation_id,COUNT(*) AS n FROM live_paper_actions "
                "WHERE run_id=? GROUP BY mutation_id",
                (rid,),
            ).fetchall()
        }
        scorecard = []
        for row in marks:
            net = float(row["equity_usd"] or 0.0) - start
            cost = float(row["cumulative_cost_usd"] or 0.0)
            scorecard.append({
                "mutation": str(row["mutation_id"]),
                "net_usd": net,
                "cost_usd": cost,
                "gross_before_modeled_cost_usd": net + cost,
                "actions": counts.get(str(row["mutation_id"]), 0),
            })
        regimes = [
            {
                "regime": str(row["inferred_regime"]),
                "ticks": int(row["n"]),
                "mean_confidence": float(row["confidence"] or 0.0),
            }
            for row in conn.execute(
                "SELECT inferred_regime,COUNT(*) AS n,AVG(regime_confidence) AS confidence "
                "FROM live_market_ticks WHERE run_id=? GROUP BY inferred_regime",
                (rid,),
            ).fetchall()
        ]
        return {
            "available": True,
            "experiment": "A",
            "run_id": rid,
            "status": str(run["status"]),
            "scorecard": sorted(scorecard, key=lambda x: x["net_usd"], reverse=True),
            "regimes": sorted(regimes, key=lambda x: x["ticks"], reverse=True),
        }
    finally:
        conn.close()


def analyze_b(path: Path) -> dict[str, Any]:
    conn = connect(path)
    if conn is None:
        return {"available": False}
    try:
        rid = latest_run_id(conn, "rotation_runs")
        if not rid:
            return {"available": False}
        run = conn.execute("SELECT * FROM rotation_runs WHERE run_id=?", (rid,)).fetchone()
        cfg = safe_config(run)
        start = float(cfg.get("start_usd") or 1000.0)
        rows = conn.execute(
            """
            SELECT mutation_id,
                   COALESCE(SUM(net_pnl_usd),0.0) AS net_usd,
                   COALESCE(SUM(entry_cost_usd),0.0)+COALESCE(SUM(exit_cost_usd),0.0) AS cost_usd,
                   COUNT(*) AS closed_legs,
                   AVG(net_return_bps) AS mean_net_bps,
                   SUM(CASE WHEN net_pnl_usd>0 THEN 1 ELSE 0 END) AS wins
            FROM rotation_legs
            WHERE run_id=? AND status='CLOSED'
            GROUP BY mutation_id
            """,
            (rid,),
        ).fetchall()
        scorecard = []
        seen = set()
        for row in rows:
            mid = str(row["mutation_id"])
            seen.add(mid)
            net = float(row["net_usd"] or 0.0)
            cost = float(row["cost_usd"] or 0.0)
            n = int(row["closed_legs"] or 0)
            scorecard.append({
                "mutation": mid,
                "net_usd": net,
                "cost_usd": cost,
                "gross_before_modeled_cost_usd": net + cost,
                "closed_legs": n,
                "win_rate": int(row["wins"] or 0) / max(1, n),
                "mean_net_bps": float(row["mean_net_bps"] or 0.0),
                "final_equity_usd": start + net,
            })
        for mid in ("stable_control", "rotation_swarm_hysteresis"):
            if mid not in seen:
                scorecard.append({
                    "mutation": mid,
                    "net_usd": 0.0,
                    "cost_usd": 0.0,
                    "gross_before_modeled_cost_usd": 0.0,
                    "closed_legs": 0,
                    "win_rate": None,
                    "mean_net_bps": None,
                    "final_equity_usd": start,
                })
        return {
            "available": True,
            "experiment": "B",
            "run_id": rid,
            "status": str(run["status"]),
            "scorecard": sorted(scorecard, key=lambda x: x["net_usd"], reverse=True),
        }
    finally:
        conn.close()


def analyze_c(path: Path) -> dict[str, Any]:
    conn = connect(path)
    if conn is None:
        return {"available": False}
    try:
        rid = latest_run_id(conn, "relative_runs")
        if not rid:
            return {"available": False}
        run = conn.execute("SELECT * FROM relative_runs WHERE run_id=?", (rid,)).fetchone()
        cfg = safe_config(run)
        start = float(cfg.get("start_usd") or 1000.0)
        marks = conn.execute(
            """
            WITH latest AS (
              SELECT mutation_id,MAX(ts) AS ts
              FROM relative_wallet_marks WHERE run_id=? GROUP BY mutation_id
            )
            SELECT w.* FROM relative_wallet_marks w
            JOIN latest x ON x.mutation_id=w.mutation_id AND x.ts=w.ts
            WHERE w.run_id=?
            """,
            (rid, rid),
        ).fetchall()
        scorecard = []
        for row in marks:
            net = float(row["total_equity_usd"] or 0.0) - start
            cost = float(row["cumulative_cost_usd"] or 0.0)
            scorecard.append({
                "mutation": str(row["mutation_id"]),
                "net_usd": net,
                "cost_usd": cost,
                "gross_before_modeled_cost_usd": net + cost,
                "switches": int(row["switches"] or 0),
                "actions": int(row["actions"] or 0),
            })
        events = [
            {
                "mutation": str(row["mutation_id"]),
                "symbol": str(row["symbol"]),
                "entry_ts": float(row["entry_ts"] or 0.0),
                "net_return_bps": float(row["net_return_bps"] or 0.0),
            }
            for row in conn.execute(
                """
                SELECT mutation_id,symbol,entry_ts,net_return_bps
                FROM relative_legs
                WHERE run_id=? AND status='CLOSED' AND exit_reason='relative_switch'
                """,
                (rid,),
            ).fetchall()
        ]
        return {
            "available": True,
            "experiment": "C",
            "run_id": rid,
            "status": str(run["status"]),
            "scorecard": sorted(scorecard, key=lambda x: x["net_usd"], reverse=True),
            "switch_events": events,
        }
    finally:
        conn.close()


def _d_events(conn: sqlite3.Connection, rid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT t.trade_id,t.mutation_id,t.ts,t.from_symbol,t.to_symbol,t.trade_usd,
               t.route_label,t.route_sides,t.total_route_cost_bps,t.modeled_cost_usd,
               t.cheapness_z,t.persistence,t.context_json,
               o.settled_10s,o.capture_10s_bps,o.net_capture_10s_bps,
               o.settled_30s,o.capture_30s_bps,o.net_capture_30s_bps,
               o.settled_60s,o.capture_60s_bps,o.net_capture_60s_bps
        FROM inventory_trades t
        JOIN inventory_signal_outcomes o ON o.trade_id=t.trade_id
        WHERE t.run_id=?
        ORDER BY t.ts,t.trade_id
        """,
        (rid,),
    ).fetchall()
    events = []
    for row in rows:
        try:
            context = json.loads(row["context_json"] or "{}")
        except Exception:
            context = {}
        item = {key: row[key] for key in row.keys() if key != "context_json"}
        item["context"] = context
        events.append(item)
    return events


def _group_event_stats(events: list[dict[str, Any]], key_fn, value_key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[float]] = {}
    for event in events:
        value = event.get(value_key)
        if value is None:
            continue
        key = str(key_fn(event))
        groups.setdefault(key, []).append(float(value))
    out = []
    for key, values in groups.items():
        positives = sum(value > 0 for value in values)
        p = exact_binomial_two_sided(positives, len(values))
        out.append({
            "key": key,
            "n": len(values),
            "mean": mean(values),
            "median": median(values),
            "positive_rate": positives / max(1, len(values)),
            "p_value": p,
        })
    out = bh_fdr(out)
    return sorted(out, key=lambda x: (x["mean"], x["n"]), reverse=True)


def analyze_d(path: Path, *, bootstrap_iterations: int, block_length: int) -> dict[str, Any]:
    conn = connect(path)
    if conn is None:
        return {"available": False}
    try:
        rid = latest_run_id(conn, "inventory_runs")
        if not rid:
            return {"available": False}
        run = conn.execute("SELECT * FROM inventory_runs WHERE run_id=?", (rid,)).fetchone()
        cfg = safe_config(run)
        start = float(cfg.get("start_usd") or 1000.0)
        marks = conn.execute(
            """
            WITH latest AS (
              SELECT mutation_id,MAX(ts) AS ts
              FROM inventory_wallet_marks WHERE run_id=? GROUP BY mutation_id
            )
            SELECT w.* FROM inventory_wallet_marks w
            JOIN latest x ON x.mutation_id=w.mutation_id AND x.ts=w.ts
            WHERE w.run_id=?
            """,
            (rid, rid),
        ).fetchall()
        scorecard = []
        equities = {str(row["mutation_id"]): float(row["total_equity_usd"] or 0.0) for row in marks}
        hold = equities.get("inventory_hold", start)
        for row in marks:
            equity = float(row["total_equity_usd"] or 0.0)
            scorecard.append({
                "mutation": str(row["mutation_id"]),
                "net_usd": equity - start,
                "excess_vs_hold_usd": equity - hold,
                "cost_usd": float(row["cumulative_cost_usd"] or 0.0),
                "rebalances": int(row["rebalances"] or 0),
                "charged_sides": int(row["charged_sides"] or 0),
            })

        events = _d_events(conn, rid)
        by_mutation: dict[str, dict[str, Any]] = {}
        for mid in sorted({str(event["mutation_id"]) for event in events}):
            mid_events = [event for event in events if str(event["mutation_id"]) == mid]
            row: dict[str, Any] = {"mutation": mid, "trades": len(mid_events)}
            for horizon in (10, 30, 60):
                value_key = f"net_capture_{horizon}s_bps"
                settled_key = f"settled_{horizon}s"
                values = [
                    float(event[value_key])
                    for event in mid_events
                    if int(event.get(settled_key) or 0) and event.get(value_key) is not None
                ]
                stats = moving_block_bootstrap_mean(
                    values,
                    block_length=block_length,
                    iterations=bootstrap_iterations,
                    seed=20260918 + horizon + len(mid),
                )
                positives = sum(value > 0 for value in values)
                stats["positive_rate"] = positives / max(1, len(values)) if values else None
                stats["binomial_p_two_sided"] = exact_binomial_two_sided(positives, len(values))
                row[f"{horizon}s"] = stats
            by_mutation[mid] = row

        primary_events = [
            event for event in events
            if str(event["mutation_id"]) == "inventory_streak"
            and int(event.get("settled_30s") or 0)
            and event.get("net_capture_30s_bps") is not None
        ]
        primary_values = [float(event["net_capture_30s_bps"]) for event in primary_events]
        primary = moving_block_bootstrap_mean(
            primary_values,
            block_length=block_length,
            iterations=bootstrap_iterations,
            seed=20260918,
        )
        primary_positive = sum(value > 0 for value in primary_values)
        primary["positive_rate"] = primary_positive / max(1, len(primary_values)) if primary_values else None
        primary["binomial_p_two_sided"] = exact_binomial_two_sided(primary_positive, len(primary_values))

        if primary_events:
            midpoint = (min(float(e["ts"]) for e in primary_events) + max(float(e["ts"]) for e in primary_events)) / 2.0
            first = [float(e["net_capture_30s_bps"]) for e in primary_events if float(e["ts"]) <= midpoint]
            second = [float(e["net_capture_30s_bps"]) for e in primary_events if float(e["ts"]) > midpoint]
        else:
            first, second = [], []
        stability = {
            "first_half_n": len(first),
            "first_half_mean_bps": mean(first) if first else None,
            "second_half_n": len(second),
            "second_half_mean_bps": mean(second) if second else None,
        }

        symbols = sorted({
            str(event["from_symbol"]) for event in primary_events
        } | {
            str(event["to_symbol"]) for event in primary_events
        })
        leave_one_out = []
        for symbol in symbols:
            values = [
                float(event["net_capture_30s_bps"])
                for event in primary_events
                if str(event["from_symbol"]) != symbol and str(event["to_symbol"]) != symbol
            ]
            leave_one_out.append({
                "excluded_symbol": symbol,
                "n": len(values),
                "mean_net_capture_30s_bps": mean(values) if values else None,
            })

        route_groups = _group_event_stats(
            primary_events,
            lambda event: event["route_label"],
            "net_capture_30s_bps",
        )
        cheap_groups = _group_event_stats(
            primary_events,
            lambda event: (
                "<=-1.5z" if float(event["cheapness_z"] or 0.0) <= -1.5
                else "-1.5..-1.0z" if float(event["cheapness_z"] or 0.0) <= -1.0
                else "-1.0..-0.5z" if float(event["cheapness_z"] or 0.0) <= -0.5
                else ">-0.5z"
            ),
            "net_capture_30s_bps",
        )
        persistence_groups = _group_event_stats(
            primary_events,
            lambda event: (
                "1.00" if float(event["persistence"] or 0.0) >= 1.0
                else "0.75..0.99" if float(event["persistence"] or 0.0) >= 0.75
                else "0.50..0.74" if float(event["persistence"] or 0.0) >= 0.50
                else "<0.50"
            ),
            "net_capture_30s_bps",
        )

        transition_groups = _group_event_stats(
            primary_events,
            lambda event: f"{event['from_symbol']}->{event['to_symbol']}",
            "net_capture_30s_bps",
        )

        horizon_alignment = _group_event_stats(
            [
                event for event in primary_events
                if isinstance((event.get("context") or {}).get("to_horizon"), dict)
                and (event.get("context") or {}).get("to_horizon")
            ],
            lambda event: ((event["context"].get("to_horizon") or {}).get("alignment") or "UNKNOWN"),
            "net_capture_30s_bps",
        )

        gross_values = [
            float(event["capture_30s_bps"])
            for event in primary_events
            if event.get("capture_30s_bps") is not None
        ]
        net_values = primary_values
        cost_values = [float(event["total_route_cost_bps"] or 0.0) for event in primary_events]

        primary_excess = next(
            (
                float(row["excess_vs_hold_usd"])
                for row in scorecard
                if row["mutation"] == "inventory_streak"
            ),
            None,
        )

        ci_low = primary.get("ci95", [None, None])[0]
        loo_means = [
            float(row["mean_net_capture_30s_bps"])
            for row in leave_one_out
            if row["mean_net_capture_30s_bps"] is not None
        ]
        halves_positive = (
            stability["first_half_mean_bps"] is not None
            and stability["second_half_mean_bps"] is not None
            and float(stability["first_half_mean_bps"]) > 0
            and float(stability["second_half_mean_bps"]) > 0
        )
        loo_positive = bool(loo_means) and min(loo_means) > 0

        if str(run["status"]) != "COMPLETE":
            verdict = "PENDING_D_COMPLETION"
        elif len(primary_values) < 10:
            verdict = "INSUFFICIENT_PRIMARY_EVENTS"
        elif float(primary.get("mean") or 0.0) <= 0:
            verdict = "NOT_SUPPORTED_IN_CURRENT_D_FORM"
        elif primary_excess is not None and primary_excess <= 0:
            verdict = "SIGNAL_POSITIVE_BUT_NOT_PORTFOLIO_HARVESTABLE"
        elif ci_low is not None and ci_low > 0 and halves_positive and loo_positive:
            verdict = "PROMISING_BUT_UNPROVEN_SINGLE_RUN"
        else:
            verdict = "PROMISING_BUT_UNPROVEN"

        return {
            "available": True,
            "experiment": "D",
            "run_id": rid,
            "status": str(run["status"]),
            "scorecard": sorted(scorecard, key=lambda x: x["excess_vs_hold_usd"], reverse=True),
            "event_stats_by_mutation": by_mutation,
            "primary_inventory_streak_30s": primary,
            "primary_excess_vs_hold_usd": primary_excess,
            "gross_mean_capture_30s_bps": mean(gross_values) if gross_values else None,
            "net_mean_capture_30s_bps": mean(net_values) if net_values else None,
            "mean_route_cost_30s_bps": mean(cost_values) if cost_values else None,
            "first_second_half": stability,
            "leave_one_symbol_out": leave_one_out,
            "route_groups": route_groups,
            "cheapness_groups": cheap_groups,
            "persistence_groups": persistence_groups,
            "transition_groups": transition_groups,
            "horizon_target_alignment_groups": horizon_alignment,
            "verdict": verdict,
        }
    finally:
        conn.close()


def progression(a: dict[str, Any], b: dict[str, Any], c: dict[str, Any], d: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    selectors = [
        ("A", a, "raw_streak"),
        ("B", b, "rotation_naive"),
        ("C", c, "relative_naive"),
        ("D", d, "inventory_naive"),
    ]
    for label, exp, mutation in selectors:
        score = next(
            (row for row in exp.get("scorecard", []) if row.get("mutation") == mutation),
            None,
        )
        if not score:
            continue
        activity = (
            score.get("actions")
            if score.get("actions") is not None
            else score.get("switches")
            if score.get("switches") is not None
            else score.get("rebalances")
        )
        rows.append({
            "experiment": label,
            "representative_mutation": mutation,
            "net_usd": score.get("net_usd"),
            "cost_usd": score.get("cost_usd"),
            "gross_before_modeled_cost_usd": score.get("gross_before_modeled_cost_usd"),
            "activity_count": activity,
        })
    return rows


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Phoenix Drizzle A-D Statistical Analysis",
        "",
        f"Overall current verdict: **{result['overall_verdict']}**",
        "",
        "This report is research-only. A single positive run does not establish live profitability.",
        "",
        "## Experiment progression",
        "",
        "| Experiment | Representative mutation | Net USD | Cost USD | Activity |",
        "|---|---|---:|---:|---:|",
    ]
    for row in result.get("progression", []):
        lines.append(
            f"| {row['experiment']} | {row['representative_mutation']} | "
            f"{float(row.get('net_usd') or 0):+.4f} | "
            f"{float(row.get('cost_usd') or 0):.4f} | "
            f"{row.get('activity_count') if row.get('activity_count') is not None else 'n/a'} |"
        )
    d = result.get("D") or {}
    if d.get("available"):
        primary = d.get("primary_inventory_streak_30s") or {}
        ci = primary.get("ci95") or [None, None]
        lines += [
            "",
            "## D primary endpoint",
            "",
            f"- inventory_streak 30s events: {primary.get('n', 0)}",
            f"- mean net capture: {primary.get('mean')}",
            f"- median net capture: {primary.get('median')}",
            f"- moving-block bootstrap 95% CI: {ci}",
            f"- positive-capture rate: {primary.get('positive_rate')}",
            f"- exact binomial two-sided p: {primary.get('binomial_p_two_sided')}",
            f"- excess versus equal-weight hold: {d.get('primary_excess_vs_hold_usd')}",
            f"- D verdict: **{d.get('verdict')}**",
            "",
            "## D stability",
            "",
            f"- first half mean: {d.get('first_second_half', {}).get('first_half_mean_bps')}",
            f"- second half mean: {d.get('first_second_half', {}).get('second_half_mean_bps')}",
            f"- gross mean 30s capture: {d.get('gross_mean_capture_30s_bps')}",
            f"- mean modeled route cost: {d.get('mean_route_cost_30s_bps')}",
            f"- net mean 30s capture: {d.get('net_mean_capture_30s_bps')}",
        ]
    lines += [
        "",
        "## Interpretation guardrail",
        "",
        "If A-D are used to refine thresholds, the refined version must face a fresh prospective run. "
        "The same observations cannot serve as both training evidence and validation evidence.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Deep stdlib-only statistical analysis across Phoenix experiments A-D")
    p.add_argument("--a", default=DEFAULTS["a"])
    p.add_argument("--b", default=DEFAULTS["b"])
    p.add_argument("--c", default=DEFAULTS["c"])
    p.add_argument("--d", default=DEFAULTS["d"])
    p.add_argument("--bootstrap-iterations", type=int, default=4000)
    p.add_argument("--block-length", type=int, default=5)
    p.add_argument("--json-out", default="data/phoenix_drizzle_A_D_analysis.json")
    p.add_argument("--markdown-out", default="data/phoenix_drizzle_A_D_analysis.md")
    args = p.parse_args()

    a = analyze_a(Path(args.a))
    b = analyze_b(Path(args.b))
    c = analyze_c(Path(args.c))
    d = analyze_d(
        Path(args.d),
        bootstrap_iterations=max(500, args.bootstrap_iterations),
        block_length=max(1, args.block_length),
    )

    if not d.get("available"):
        overall = "PENDING_EXPERIMENT_D"
    else:
        overall = str(d.get("verdict") or "PENDING")
        if overall == "PROMISING_BUT_UNPROVEN_SINGLE_RUN":
            overall = "PROMISING_BUT_UNPROVEN"
    result = {
        "schema": "phoenix_drizzle_A_D_statistical_analysis_v1",
        "authority": "research_evidence_only_no_execution_or_promotion_authority",
        "overall_verdict": overall,
        "A": a,
        "B": b,
        "C": c,
        "D": d,
        "progression": progression(a, b, c, d),
        "caveat": (
            "A-D are sequential development experiments, not four independent replications. "
            "Any refinement selected from these results requires fresh prospective validation."
        ),
    }

    json_path = Path(args.json_out)
    md_path = Path(args.markdown_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(markdown_report(result), encoding="utf-8")

    print("Phoenix Drizzle A-D statistical analysis")
    print("----------------------------------------")
    print(f"overall_verdict={overall}")
    print()
    for row in result["progression"]:
        print(
            f"{row['experiment']} {row['representative_mutation']:24s} "
            f"net={float(row.get('net_usd') or 0):+8.4f} "
            f"cost={float(row.get('cost_usd') or 0):7.4f} "
            f"activity={row.get('activity_count')}"
        )
    if d.get("available"):
        primary = d.get("primary_inventory_streak_30s") or {}
        ci = primary.get("ci95") or [None, None]
        print()
        print("D primary: inventory_streak @ 30s")
        print(
            f"n={primary.get('n',0)} mean={primary.get('mean')} "
            f"median={primary.get('median')} ci95={ci} "
            f"positive_rate={primary.get('positive_rate')} "
            f"binomial_p={primary.get('binomial_p_two_sided')}"
        )
        print(
            f"excess_vs_hold_usd={d.get('primary_excess_vs_hold_usd')} "
            f"D_verdict={d.get('verdict')}"
        )
    print()
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
