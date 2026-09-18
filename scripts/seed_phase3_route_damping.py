#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.beast_route_damping import HivenanceRouteDampener


def _candidate_from_rows(order: dict, forecast_payload: dict) -> dict:
    inputs = forecast_payload.get("inputs") if isinstance(forecast_payload.get("inputs"), dict) else {}
    regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
    regime_hint = inputs.get("regime_hint") or regime_inputs.get("regime_hint")
    return {
        "model_id": order.get("model_id"),
        "hypothesis": order.get("hypothesis"),
        "regime_hint": regime_hint,
        "cohort_bucket": inputs.get("cohort_bucket"),
        "symbol_class": inputs.get("symbol_class"),
        "symbol": order.get("symbol"),
        "horizon_seconds": forecast_payload.get("horizon_seconds") or inputs.get("horizon_seconds"),
        "direction": order.get("direction") or forecast_payload.get("direction"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed BEAST-style Phase-3 route damping from existing simulations.")
    parser.add_argument("--database", type=Path, default=ROOT / "data/swarm_data.db")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--path", type=Path)
    parser.add_argument("--suppress-at", type=float, default=1000.0)
    parser.add_argument("--half-life-sec", type=float, default=900.0)
    args = parser.parse_args()

    db_path = args.database if args.database.is_absolute() else ROOT / args.database
    damping_path = args.path or (db_path.parent / "phase3_route_damping.json")
    store = DataStoreAgent(str(db_path))
    dampener = HivenanceRouteDampener(
        path=damping_path,
        suppress_at=args.suppress_at,
        half_life_seconds=args.half_life_sec,
    )
    rows = store.conn.execute(
        """
        SELECT o.model_id, o.hypothesis, o.symbol, o.direction, o.order_policy,
               o.scenario, o.status, o.profitable_after_costs, o.net_return_bps,
               o.completed_ts, o.payload AS order_payload, f.payload AS forecast_payload
        FROM simulated_orders o
        LEFT JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
        ORDER BY o.rowid DESC
        LIMIT ?
        """,
        (max(1, int(args.limit)),),
    ).fetchall()
    columns = [
        "model_id", "hypothesis", "symbol", "direction", "order_policy",
        "scenario", "status", "profitable_after_costs", "net_return_bps",
        "completed_ts", "order_payload", "forecast_payload",
    ]
    events: dict[str, int] = {}
    route_events: dict[tuple[str, str], int] = {}
    routes_seen: set[str] = set()
    for raw in rows:
        order = dict(zip(columns, raw))
        try:
            order_payload = json.loads(order.get("order_payload") or "{}")
        except Exception:
            order_payload = {}
        try:
            forecast_payload = json.loads(order.get("forecast_payload") or "{}")
        except Exception:
            forecast_payload = {}
        candidate = _candidate_from_rows(order, forecast_payload if isinstance(forecast_payload, dict) else {})
        diagnostics = order_payload.get("diagnostics") if isinstance(order_payload.get("diagnostics"), dict) else {}
        causes = [str(item) for item in (diagnostics.get("failure_causes") or []) if str(item or "").strip()]
        if order.get("status") == "COMPLETED" and int(order.get("profitable_after_costs") or 0) and not causes:
            causes = ["profitable_after_costs"]
        elif order.get("status") == "COMPLETED" and not causes:
            causes = ["success" if float(order.get("net_return_bps") or 0.0) > 0.0 else "cost_drag"]
        elif order.get("status") == "EXPIRED" and not causes:
            causes = ["late_entry_or_missed_fill"]
        elif order.get("status") == "REJECTED" and not causes:
            causes = ["venue_rejection"]
        route_id = dampener.route_id_from_candidate(
            candidate,
            policy=str(order.get("order_policy") or ""),
            scenario=str(order.get("scenario") or ""),
        )
        routes_seen.add(route_id)
        for cause in causes:
            route_events[(route_id, cause)] = route_events.get((route_id, cause), 0) + 1
            events[cause] = events.get(cause, 0) + 1
    applied = dampener.record_many(route_events)
    snapshot = dampener.snapshot(limit=20)
    print(json.dumps({
        "database": str(db_path),
        "damping_path": str(damping_path),
        "rows_examined": len(rows),
        "routes_seen": len(routes_seen),
        "route_event_pairs": len(route_events),
        "bulk_apply": applied,
        "events": events,
        "suppressed_count": snapshot.get("suppressed_count"),
        "top_routes": snapshot.get("routes", [])[:5],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
