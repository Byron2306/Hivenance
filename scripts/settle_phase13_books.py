#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from strategies.relative_value_lab.phase13_book_ledger import Phase13BookLedger
from strategies.volatility_breakout.shadow_flight import ShadowSettlementEngine


def _connect_ro(path:Path):
    con=sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True)
    con.row_factory=sqlite3.Row
    return con


def _observations(
    con:sqlite3.Connection,
    *,
    symbol:str,
    created_ts:float,
    target_ts:float,
    tolerance_sec:float,
)->list[dict[str,Any]]:
    rows=con.execute(
        """SELECT ts,symbol,venue,price,spread_bps,depth_usd_25bps,data_quality
        FROM observation_snapshots
        WHERE symbol=? AND ts>=? AND ts<=?
        ORDER BY ts""",
        (str(symbol),float(created_ts),float(target_ts+tolerance_sec)),
    ).fetchall()
    return [dict(row) for row in rows]


def main()->int:
    ap=argparse.ArgumentParser(description="Settle mature Phase-13 forecast-book rows from public observations")
    ap.add_argument("--freeze",type=Path,default=Path("data/phase13_experiment_freeze.json"))
    ap.add_argument("--ledger",type=Path,default=Path("data/hivenance_phase13_books.db"))
    ap.add_argument("--market-db",type=Path,default=Path("data/swarm_data.db"))
    ap.add_argument("--out",type=Path,default=Path("data/phase13_settlement_book.json"))
    ap.add_argument("--tolerance-sec",type=float,default=1800.0)
    ap.add_argument("--limit",type=int,default=10000)
    ap.add_argument("--as-of-ts",type=float,default=None)
    args=ap.parse_args()

    freeze=json.loads(args.freeze.read_text(encoding="utf-8"))
    freeze_id=str(freeze.get("freeze_id") or "")
    if not freeze_id:
        raise ValueError("phase13_freeze_id_missing")

    now_ts=float(time.time() if args.as_of_ts is None else args.as_of_ts)
    cfg=SimpleNamespace(
        exchange="kraken",
        phase5_shadow_entry_latency_ms=250.0,
        phase5_shadow_chase_timeout_sec=30.0,
        phase3_max_slippage_bps=75.0,
        phase3_maker_fee_bps=16.0,
        phase3_taker_fee_bps=26.0,
    )
    engine=ShadowSettlementEngine(cfg)
    ledger=Phase13BookLedger(args.ledger)
    market=_connect_ro(args.market_db)

    settled=0
    abstained=0
    awaiting=0
    no_tape=0
    try:
        pending=ledger.pending_forecasts(
            freeze_id=freeze_id,
            target_time_ms=int(now_ts*1000),
            limit=int(args.limit),
        )
        for row in pending:
            payload=dict(row.get("payload") or {})
            created_ts=float(row["timestamp_ms"])/1000.0
            target_ts=created_ts+float(row["horizon_seconds"])
            if target_ts>now_ts:
                awaiting+=1
                continue

            abstain=bool(payload.get("abstain"))
            direction=str(payload.get("direction") or "ABSTAIN").upper()
            entry_price=payload.get("entry_price")
            regime=str(payload.get("regime") or "unknown")

            if abstain or direction=="ABSTAIN":
                ledger.persist_settlement(
                    forecast_row_id=row["row_id"],
                    freeze_id=row["freeze_id"],
                    book_id=row["book_id"],
                    world_state_id=row["world_state_id"],
                    world_state_hash=row["world_state_hash"],
                    symbol=row["symbol"],
                    timestamp_ms=row["timestamp_ms"],
                    horizon_seconds=row["horizon_seconds"],
                    model_id=row["model_id"],
                    settled_ts=now_ts,
                    realized_net_bps=0.0,
                    realized_cost_bps=0.0,
                    fill_status="ABSTAIN",
                    filled=False,
                    payload={
                        "abstain":True,
                        "direction":"ABSTAIN",
                        "regime":regime,
                        "expected_cost_bps":payload.get("expected_cost_bps"),
                        "expected_net_bps":payload.get("expected_net_bps"),
                        "selected":None,
                    },
                )
                settled+=1
                abstained+=1
                continue

            if entry_price is None:
                no_tape+=1
                continue

            tape=_observations(
                market,
                symbol=row["symbol"],
                created_ts=created_ts,
                target_ts=target_ts,
                tolerance_sec=float(args.tolerance_sec),
            )
            if not tape or not any(float(x.get("ts") or 0.0)>=target_ts for x in tape):
                no_tape+=1
                continue

            first=tape[0]
            intent={
                "shadow_intent_id":"phase13:"+row["row_id"],
                "forecast_id":row["row_id"],
                "order_policy":"market",
                "venue":str(first.get("venue") or "kraken"),
                "symbol":row["symbol"],
                "direction":direction,
                "side":"buy" if direction=="UP" else "sell",
                "order_type":"market",
                "time_in_force":"IOC",
                "reference_price":float(entry_price),
                "limit_price":None,
                "notional_usd":5.0,
                "predicted_cost_bps":float(payload.get("expected_cost_bps") or 0.0),
                "created_ts":created_ts,
                "target_ts":target_ts,
                "data_quality":float(first.get("data_quality") or 0.0),
            }
            result=engine.settle(intent,tape,settled_ts=now_ts)
            if result is None:
                no_tape+=1
                continue

            ledger.persist_settlement(
                forecast_row_id=row["row_id"],
                freeze_id=row["freeze_id"],
                book_id=row["book_id"],
                world_state_id=row["world_state_id"],
                world_state_hash=row["world_state_hash"],
                symbol=row["symbol"],
                timestamp_ms=row["timestamp_ms"],
                horizon_seconds=row["horizon_seconds"],
                model_id=row["model_id"],
                settled_ts=float(result.settled_ts),
                realized_net_bps=float(result.net_return_bps),
                realized_cost_bps=float(result.observed_total_cost_bps),
                fill_status=str(result.status),
                filled=bool(result.fill_ratio>0),
                payload={
                    "abstain":False,
                    "direction":direction,
                    "regime":regime,
                    "expected_cost_bps":payload.get("expected_cost_bps"),
                    "expected_net_bps":payload.get("expected_net_bps"),
                    "fill_model":result.fill_model,
                    "fill_ratio":result.fill_ratio,
                    "gross_directional_return_bps":result.gross_directional_return_bps,
                    "data_quality":result.data_quality,
                    "selected":None,
                },
            )
            settled+=1

        export=ledger.export_settlements(freeze_id=freeze_id)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(export,indent=2,sort_keys=True),encoding="utf-8")

        print("HIVENANCE_PHASE13_SETTLEMENT")
        print("freeze_id=",freeze_id)
        print("pending_examined=",len(pending))
        print("settled=",settled)
        print("abstained=",abstained)
        print("awaiting=",awaiting)
        print("no_mature_public_tape=",no_tape)
        print("total_exported=",len(export.get("rows") or []))
        print("execution_eligible=False")
        print("promotion_eligible=False")
        print("out=",args.out)
        return 0
    finally:
        market.close()
        ledger.close()


if __name__=="__main__":
    raise SystemExit(main())
