#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from agents.nurse import NurseAgent


def main() -> int:
    p=argparse.ArgumentParser(description="Report inventory drizzle harvest lab")
    p.add_argument("--database",default="data/live_inventory_drizzle_lab.db")
    p.add_argument("--run-id")
    p.add_argument("--latest",action="store_true")
    args=p.parse_args()
    path=Path(args.database)
    if not path.exists():
        print(f"No inventory-drizzle database yet: {path}")
        return 0

    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    try:
        if args.run_id:
            run=conn.execute("SELECT * FROM inventory_runs WHERE run_id=?",(args.run_id,)).fetchone()
        else:
            run=conn.execute("SELECT * FROM inventory_runs ORDER BY started_ts DESC LIMIT 1").fetchone()
        if not run:
            print("No inventory-drizzle run found.")
            return 0
        rid=str(run["run_id"])
        try:
            cfg=json.loads(run["config_json"] or "{}")
        except Exception:
            cfg={}
        start=float(cfg.get("start_usd",1000.0))

        print(f"Phoenix Inventory Drizzle // {rid}")
        print(f"status={run['status']} authority={run['authority']}")
        print("objective=harvest_small_relative_oscillations_with_inventory_after_costs")
        print(f"learning_authority={run['learning_authority']}")
        print()

        rows=conn.execute(
            """
            SELECT w.*
            FROM inventory_wallet_marks w
            JOIN (
              SELECT mutation_id,MAX(ts) AS max_ts
              FROM inventory_wallet_marks WHERE run_id=? GROUP BY mutation_id
            ) x ON x.mutation_id=w.mutation_id AND x.max_ts=w.ts
            WHERE w.run_id=?
            ORDER BY w.total_equity_usd DESC
            """,(rid,rid)
        ).fetchall()
        scores={str(row["mutation_id"]):float(row["total_equity_usd"] or 0.0) for row in rows}
        hold=scores.get("inventory_hold",start)

        print("Inventory scorecard")
        print("-------------------")
        for row in rows:
            mid=str(row["mutation_id"])
            equity=float(row["total_equity_usd"] or 0.0)
            print(
                f"{mid:27s} equity={equity:10.4f} net={equity-start:+9.4f} "
                f"excess_vs_hold={equity-hold:+9.4f} "
                f"cost={float(row['cumulative_cost_usd'] or 0):7.4f} "
                f"rebalances={int(row['rebalances'] or 0):4d} "
                f"sides={int(row['charged_sides'] or 0):4d} "
                f"max_weight={float(row['max_weight'] or 0)*100:5.1f}%"
            )

        route_rows=conn.execute(
            """
            SELECT route_label,COUNT(*) AS n,
                   AVG(total_route_cost_bps) AS mean_cost_bps,
                   SUM(modeled_cost_usd) AS total_cost_usd
            FROM inventory_trades
            WHERE run_id=?
            GROUP BY route_label
            ORDER BY n DESC
            """,(rid,)
        ).fetchall()
        if route_rows:
            print()
            print("Route economics")
            print("---------------")
            for row in route_rows:
                print(
                    f"{str(row['route_label']):16s} n={int(row['n']):4d} "
                    f"mean_cost={float(row['mean_cost_bps'] or 0):6.2f}bps "
                    f"cost_usd={float(row['total_cost_usd'] or 0):8.4f}"
                )

        horizon_rows=conn.execute(
            """
            SELECT t.mutation_id,
                   COUNT(CASE WHEN o.settled_10s=1 THEN 1 END) AS n10,
                   AVG(CASE WHEN o.settled_10s=1 THEN o.net_capture_10s_bps END) AS m10,
                   COUNT(CASE WHEN o.settled_30s=1 THEN 1 END) AS n30,
                   AVG(CASE WHEN o.settled_30s=1 THEN o.net_capture_30s_bps END) AS m30,
                   COUNT(CASE WHEN o.settled_60s=1 THEN 1 END) AS n60,
                   AVG(CASE WHEN o.settled_60s=1 THEN o.net_capture_60s_bps END) AS m60
            FROM inventory_trades t
            JOIN inventory_signal_outcomes o ON o.trade_id=t.trade_id
            WHERE t.run_id=?
            GROUP BY t.mutation_id
            ORDER BY t.mutation_id
            """,(rid,)
        ).fetchall()
        if horizon_rows:
            print()
            print("Net relative capture after modeled route cost")
            print("---------------------------------------------")
            for row in horizon_rows:
                print(
                    f"{str(row['mutation_id']):27s} "
                    f"10s n={int(row['n10'] or 0):3d} mean={float(row['m10'] or 0):+7.2f}bps | "
                    f"30s n={int(row['n30'] or 0):3d} mean={float(row['m30'] or 0):+7.2f}bps | "
                    f"60s n={int(row['n60'] or 0):3d} mean={float(row['m60'] or 0):+7.2f}bps"
                )

        best=conn.execute(
            """
            SELECT mutation_id,from_symbol,to_symbol,cheapness_z,persistence,
                   gross_edge_bps,net_edge_bps,total_route_cost_bps,route_label,
                   batch_confirmations
            FROM inventory_trades
            WHERE run_id=?
            ORDER BY net_edge_bps DESC
            LIMIT 10
            """,(rid,)
        ).fetchall()
        if best:
            print()
            print("Highest expected-edge rebalances")
            print("--------------------------------")
            for row in best:
                print(
                    f"{str(row['mutation_id']):27s} {row['from_symbol']} -> {row['to_symbol']} "
                    f"cheap={float(row['cheapness_z'] or 0):+.2f}z "
                    f"persist={float(row['persistence'] or 0):.2f} "
                    f"edge={float(row['net_edge_bps'] or 0):+7.2f}bps "
                    f"cost={float(row['total_route_cost_bps'] or 0):5.2f}bps "
                    f"{row['route_label']} batch={int(row['batch_confirmations'] or 0)}"
                )

        latency=conn.execute(
            "SELECT AVG(cycle_latency_ms),MAX(cycle_latency_ms) "
            "FROM inventory_wallet_marks WHERE run_id=?",(rid,)
        ).fetchone()
        print()
        print(f"Cycle latency mean={float(latency[0] or 0):.1f}ms max={float(latency[1] or 0):.1f}ms")
    finally:
        conn.close()

    nurse=NurseAgent().review_inventory_drizzle_lab(str(path),rid)
    print()
    print("Nurse inventory-drizzle learning")
    print("--------------------------------")
    print(
        f"trades={nurse.get('trades',0)} "
        f"candidate_crystals={nurse.get('candidate_crystals',0)} "
        f"positive={nurse.get('positive_candidate_crystals',0)} "
        f"negative={nurse.get('negative_candidate_crystals',0)}"
    )
    for row in nurse.get("final_scorecard") or []:
        print(
            f"{str(row['mutation_id']):27s} net={float(row['net_usd']):+8.4f} "
            f"excess_vs_hold={float(row['excess_vs_hold_usd']):+8.4f} "
            f"cost={float(row['modeled_cost_usd']):7.4f} "
            f"rebalances={int(row['rebalances']):3d}"
        )

    for title,key in (
        ("Learning by route","by_route"),
        ("Learning by relative cheapness","by_relative_cheapness"),
        ("Learning by streak persistence","by_streak_persistence"),
    ):
        rows2=nurse.get(key) or []
        if rows2:
            print()
            print(title)
            for row in rows2:
                print(
                    f"  {str(row['key']):14s} n={int(row['samples']):3d} "
                    f"win={float(row['win_rate'])*100:5.1f}% "
                    f"mean_net_capture={float(row['mean_net_capture_bps']):+7.2f}bps"
                )

    horizons=nurse.get("by_horizon") or {}
    if horizons:
        print()
        print("Learning by settlement horizon")
        for horizon in ("10s","30s","60s"):
            for row in horizons.get(horizon) or []:
                print(
                    f"  {horizon:3s} {str(row['key']):27s} "
                    f"n={int(row['samples']):3d} win={float(row['win_rate'])*100:5.1f}% "
                    f"mean={float(row['mean_net_capture_bps']):+7.2f}bps"
                )

    strong=nurse.get("strong_candidate_memories") or []
    if strong:
        print()
        print("Strong candidate memories (NOT promoted)")
        for row in strong[:12]:
            print(
                f"  {row['family']:19s} {row['transition']:18s} "
                f"net={float(row['net_capture_bps']):+7.2f}bps "
                f"cheap={float(row['cheapness_z']):+.2f}z "
                f"persist={float(row['persistence']):.2f} "
                f"route_sides={int(row['route_sides'])}"
            )

    print()
    print(f"promotion_state={nurse.get('promotion_state','NOT_PROMOTED')}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
