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
    p=argparse.ArgumentParser(description="Report relative cheapness + streak drizzle lab")
    p.add_argument("--database",default="data/live_relative_drizzle_lab.db")
    p.add_argument("--run-id")
    p.add_argument("--latest",action="store_true")
    args=p.parse_args()
    path=Path(args.database)
    if not path.exists():
        print(f"No relative-drizzle database yet: {path}")
        return 0

    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    try:
        if args.run_id:
            run=conn.execute(
                "SELECT * FROM relative_runs WHERE run_id=?",(args.run_id,)
            ).fetchone()
        else:
            run=conn.execute(
                "SELECT * FROM relative_runs ORDER BY started_ts DESC LIMIT 1"
            ).fetchone()
        if not run:
            print("No relative-drizzle run found.")
            return 0
        rid=str(run["run_id"])
        try:
            cfg=json.loads(run["config_json"] or "{}")
        except Exception:
            cfg={}
        start=float(cfg.get("start_usd",1000.0))
        print(f"Phoenix Relative Drizzle // {rid}")
        print(f"status={run['status']} authority={run['authority']}")
        print(f"objective=tiny_incremental_relative_gains_after_costs")
        print(f"learning_authority={run['learning_authority']}")
        print()

        marks=conn.execute(
            """
            SELECT w.*
            FROM relative_wallet_marks w
            JOIN (
              SELECT mutation_id,MAX(ts) AS max_ts
              FROM relative_wallet_marks WHERE run_id=?
              GROUP BY mutation_id
            ) x ON x.mutation_id=w.mutation_id AND x.max_ts=w.ts
            WHERE w.run_id=?
            ORDER BY w.total_equity_usd DESC
            """,(rid,rid)
        ).fetchall()

        print("Drizzle scorecard")
        print("-----------------")
        for row in marks:
            equity=float(row["total_equity_usd"] or 0.0)
            net=equity-start
            print(
                f"{str(row['mutation_id']):28s} equity={equity:10.4f} "
                f"net={net:+9.4f} cost={float(row['cumulative_cost_usd'] or 0):7.4f} "
                f"switches={int(row['switches'] or 0):4d} actions={int(row['actions'] or 0):4d} "
                f"held={row['held_asset']}"
            )

        latest_pair=conn.execute(
            """
            SELECT mutation_id,incumbent,challenger,cheapness_z,pair_drawdown_bps,
                   relative_1s_bps,relative_3s_bps,streak_persistence,
                   gross_edge_bps,switch_cost_bps,net_edge_bps,admissible,rank
            FROM relative_pair_scores
            WHERE run_id=?
              AND ts=(SELECT MAX(ts) FROM relative_pair_scores WHERE run_id=?)
            ORDER BY mutation_id,rank
            """,(rid,rid)
        ).fetchall()
        if latest_pair:
            print()
            print("Current best relative challenger by mutation")
            print("-------------------------------------------")
            seen=set()
            for row in latest_pair:
                mid=str(row["mutation_id"])
                if mid in seen:
                    continue
                seen.add(mid)
                print(
                    f"{mid:28s} {row['incumbent']} -> {row['challenger']} "
                    f"cheap={float(row['cheapness_z']):+.2f}z "
                    f"r1={float(row['relative_1s_bps']):+.2f}bps "
                    f"r3={float(row['relative_3s_bps']):+.2f}bps "
                    f"persist={float(row['streak_persistence']):.2f} "
                    f"net_edge={float(row['net_edge_bps']):+.2f}bps "
                    f"admissible={bool(row['admissible'])}"
                )

        transitions=conn.execute(
            """
            SELECT json_extract(exit_context_json,'$.challenger') AS challenger,
                   symbol AS incumbent,
                   mutation_id,
                   COUNT(*) AS n,
                   AVG(net_return_bps) AS mean_bps,
                   SUM(CASE WHEN net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   SUM(net_pnl_usd) AS net_usd,
                   AVG(duration_sec) AS mean_duration
            FROM relative_legs
            WHERE run_id=? AND status='CLOSED' AND exit_reason='relative_switch'
            GROUP BY mutation_id,incumbent,challenger
            ORDER BY mean_bps DESC
            LIMIT 12
            """,(rid,)
        ).fetchall()
        if transitions:
            print()
            print("Observed relative transitions")
            print("-----------------------------")
            for row in transitions:
                n=int(row["n"] or 0)
                wins=int(row["wins"] or 0)
                print(
                    f"{str(row['mutation_id']):28s} {row['incumbent']} -> {row['challenger']} "
                    f"n={n:3d} win={wins/max(1,n)*100:5.1f}% "
                    f"mean={float(row['mean_bps'] or 0):+7.2f}bps "
                    f"net={float(row['net_usd'] or 0):+8.4f}USD "
                    f"dur={float(row['mean_duration'] or 0):5.1f}s"
                )

        latency=conn.execute(
            "SELECT AVG(cycle_latency_ms),MAX(cycle_latency_ms) "
            "FROM relative_wallet_marks WHERE run_id=?",(rid,)
        ).fetchone()
        print()
        print(
            f"Cycle latency mean={float(latency[0] or 0):.1f}ms "
            f"max={float(latency[1] or 0):.1f}ms"
        )
    finally:
        conn.close()

    nurse=NurseAgent().review_relative_drizzle_lab(str(path),rid)
    print()
    print("Nurse relative-drizzle learning")
    print("-------------------------------")
    print(
        f"closed_switch_legs={nurse.get('closed_switch_legs',0)} "
        f"candidate_crystals={nurse.get('candidate_crystals',0)} "
        f"positive={nurse.get('positive_candidate_crystals',0)} "
        f"negative={nurse.get('negative_candidate_crystals',0)}"
    )
    for row in nurse.get("by_mutation") or []:
        print(
            f"{str(row['key']):28s} n={int(row['samples']):3d} "
            f"win={float(row['win_rate'])*100:5.1f}% "
            f"mean_net={float(row['mean_net_return_bps']):+7.2f}bps "
            f"net={float(row['net_pnl_usd']):+8.4f}USD "
            f"dur={float(row['mean_duration_sec']):5.1f}s"
        )

    cheap=nurse.get("by_relative_cheapness") or []
    if cheap:
        print()
        print("Learning by relative cheapness")
        for row in cheap:
            print(
                f"  {str(row['key']):12s} n={int(row['samples']):3d} "
                f"win={float(row['win_rate'])*100:5.1f}% "
                f"mean_net={float(row['mean_net_return_bps']):+7.2f}bps"
            )

    persist=nurse.get("by_streak_persistence") or []
    if persist:
        print()
        print("Learning by streak persistence")
        for row in persist:
            print(
                f"  {str(row['key']):12s} n={int(row['samples']):3d} "
                f"win={float(row['win_rate'])*100:5.1f}% "
                f"mean_net={float(row['mean_net_return_bps']):+7.2f}bps"
            )

    strong=nurse.get("strong_candidate_memories") or []
    if strong:
        print()
        print("Strong candidate memories (NOT promoted)")
        for row in strong[:10]:
            print(
                f"  {row['family']:19s} {row['incumbent']} -> {row['challenger']} "
                f"cheap={float(row['cheapness_z']):+.2f}z "
                f"persist={float(row['streak_persistence']):.2f} "
                f"net={float(row['net_return_bps']):+.2f}bps "
                f"strength={float(row['evidence_strength']):.2f}"
            )

    print()
    print(f"promotion_state={nurse.get('promotion_state','NOT_PROMOTED')}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
