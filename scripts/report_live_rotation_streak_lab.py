#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.nurse import NurseAgent


def latest_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT run_id,status,started_ts,ended_ts,authority,learning_authority "
        "FROM rotation_runs ORDER BY started_ts DESC LIMIT 1"
    ).fetchone()


def main() -> int:
    p=argparse.ArgumentParser(description="Report Phoenix cross-asset rotation and Nurse learning")
    p.add_argument("--database",default="data/live_rotation_streak_lab.db")
    p.add_argument("--run-id",default=None)
    p.add_argument("--latest",action="store_true")
    args=p.parse_args()
    path=Path(args.database)
    if not path.exists():
        print(f"waiting for rotation database: {path}")
        return 0

    conn=sqlite3.connect(path)
    conn.row_factory=sqlite3.Row
    try:
        if args.run_id:
            run=conn.execute(
                "SELECT run_id,status,started_ts,ended_ts,authority,learning_authority "
                "FROM rotation_runs WHERE run_id=?",(args.run_id,)
            ).fetchone()
        else:
            run=latest_run(conn)
        if not run:
            print("No rotation runs yet.")
            return 0
        rid=str(run["run_id"])
        print(f"Phoenix Rotation Lab // {rid}")
        print(f"status={run['status']} authority={run['authority']}")
        print(f"learning_authority={run['learning_authority']}")
        print("\nWallet scorecard")
        print("----------------")
        rows=conn.execute(
            """
            SELECT w.mutation_id,w.equity_usd,w.held_asset,w.cost_usd,w.actions,w.cycle_latency_ms
            FROM rotation_wallet_marks w
            JOIN (
              SELECT mutation_id,MAX(ts) AS max_ts
              FROM rotation_wallet_marks
              WHERE run_id=?
              GROUP BY mutation_id
            ) x ON x.mutation_id=w.mutation_id AND x.max_ts=w.ts
            WHERE w.run_id=?
            ORDER BY w.equity_usd DESC
            """,(rid,rid)
        ).fetchall()
        start_row=conn.execute(
            "SELECT config_json FROM rotation_runs WHERE run_id=?",(rid,)
        ).fetchone()
        try:
            start=float(json.loads(start_row[0] or "{}").get("start_usd",1000.0))
        except Exception:
            start=1000.0
        for row in rows:
            net=float(row["equity_usd"] or 0)-start
            print(
                f"{str(row['mutation_id']):28s} equity={float(row['equity_usd']):10.4f} "
                f"net={net:+9.4f} cost={float(row['cost_usd'] or 0):7.4f} "
                f"actions={int(row['actions'] or 0):4d} held={row['held_asset']}"
            )

        latency=conn.execute(
            "SELECT AVG(cycle_latency_ms),MAX(cycle_latency_ms) "
            "FROM rotation_wallet_marks WHERE run_id=?",(rid,)
        ).fetchone()
        print(f"\nMean cycle latency={float(latency[0] or 0):.1f}ms max={float(latency[1] or 0):.1f}ms")

        recent=conn.execute(
            "SELECT ts,symbol,net_score_bps,rank,regime,positive_votes,positive_families "
            "FROM rotation_scores WHERE run_id=? ORDER BY ts DESC,rank ASC LIMIT 8",(rid,)
        ).fetchall()
        print("\nLatest opportunity ranking")
        print("--------------------------")
        for row in recent:
            print(
                f"#{int(row['rank'])} {str(row['symbol']):10s} "
                f"net_score={float(row['net_score_bps']):+7.2f}bps "
                f"regime={str(row['regime']):8s} votes+={int(row['positive_votes'])} "
                f"families+={int(row['positive_families'])}"
            )
    finally:
        conn.close()

    review=NurseAgent().review_rotation_lab(str(path),rid)
    print("\nNurse learning review")
    print("---------------------")
    print(
        f"closed_legs={review.get('closed_legs',0)} "
        f"candidate_crystals={review.get('candidate_crystals',0)} "
        f"positive={review.get('positive_candidate_crystals',0)} "
        f"negative={review.get('negative_candidate_crystals',0)}"
    )
    for row in review.get("by_mutation") or []:
        print(
            f"{str(row['key']):28s} samples={int(row['samples']):3d} "
            f"win_rate={float(row['win_rate'])*100:6.1f}% "
            f"mean_net={float(row['mean_net_return_bps']):+8.2f}bps "
            f"net_usd={float(row['net_pnl_usd']):+8.4f}"
        )
    rb=review.get("rebound_after_retrace") or {}
    nr=review.get("non_rebound") or {}
    print(
        f"rebound_after_retrace: n={rb.get('samples',0)} "
        f"win={float(rb.get('win_rate',0))*100:.1f}% "
        f"mean_net={float(rb.get('mean_net_return_bps',0)):+.2f}bps"
    )
    print(
        f"non_rebound:          n={nr.get('samples',0)} "
        f"win={float(nr.get('win_rate',0))*100:.1f}% "
        f"mean_net={float(nr.get('mean_net_return_bps',0)):+.2f}bps"
    )
    strong=review.get("strong_candidate_memories") or []
    if strong:
        print("\nStrong candidate memories (NOT promoted)")
        for item in strong[:8]:
            print(
                f"{item['family']:19s} {item['symbol']:10s} "
                f"regime={item['regime']:8s} strength={float(item['evidence_strength']):.2f} "
                f"net={float(item['net_return_bps']):+.2f}bps"
            )
    print(f"\npromotion_state={review.get('promotion_state','NOT_PROMOTED')}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
