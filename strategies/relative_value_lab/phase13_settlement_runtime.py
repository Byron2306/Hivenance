from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .phase13_book_ledger import Phase13BookLedger
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


def settle_mature_phase13_books(
    *,
    freeze_id:str,
    ledger_path:str|Path="data/hivenance_phase13_books.db",
    market_db_path:str|Path="data/swarm_data.db",
    as_of_ts:float|None=None,
    tolerance_sec:float=1800.0,
    limit:int=10000,
)->dict[str,Any]:
    now_ts=float(time.time() if as_of_ts is None else as_of_ts)
    cfg=SimpleNamespace(
        exchange="kraken",
        phase5_shadow_entry_latency_ms=250.0,
        phase5_shadow_chase_timeout_sec=30.0,
        phase3_max_slippage_bps=75.0,
        phase3_maker_fee_bps=16.0,
        phase3_taker_fee_bps=26.0,
    )
    engine=ShadowSettlementEngine(cfg)
    ledger=Phase13BookLedger(ledger_path)
    market=_connect_ro(Path(market_db_path))

    settled=0
    abstained=0
    awaiting=0
    no_tape=0
    errors=[]
    try:
        pending=ledger.pending_forecasts(
            freeze_id=str(freeze_id),
            target_time_ms=int(now_ts*1000),
            limit=int(limit),
        )
        for row in pending:
            try:
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
                        freeze_id=row["freeze_id"],book_id=row["book_id"],
                        world_state_id=row["world_state_id"],world_state_hash=row["world_state_hash"],
                        symbol=row["symbol"],timestamp_ms=row["timestamp_ms"],
                        horizon_seconds=row["horizon_seconds"],model_id=row["model_id"],
                        settled_ts=now_ts,realized_net_bps=0.0,realized_cost_bps=0.0,
                        fill_status="ABSTAIN",filled=False,
                        payload={
                            "abstain":True,"direction":"ABSTAIN","regime":regime,
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
                    market,symbol=row["symbol"],created_ts=created_ts,
                    target_ts=target_ts,tolerance_sec=float(tolerance_sec),
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
                    "order_type":"market","time_in_force":"IOC",
                    "reference_price":float(entry_price),"limit_price":None,
                    "notional_usd":5.0,
                    "predicted_cost_bps":float(payload.get("expected_cost_bps") or 0.0),
                    "created_ts":created_ts,"target_ts":target_ts,
                    "data_quality":float(first.get("data_quality") or 0.0),
                }
                result=engine.settle(intent,tape,settled_ts=now_ts)
                if result is None:
                    no_tape+=1
                    continue

                ledger.persist_settlement(
                    forecast_row_id=row["row_id"],
                    freeze_id=row["freeze_id"],book_id=row["book_id"],
                    world_state_id=row["world_state_id"],world_state_hash=row["world_state_hash"],
                    symbol=row["symbol"],timestamp_ms=row["timestamp_ms"],
                    horizon_seconds=row["horizon_seconds"],model_id=row["model_id"],
                    settled_ts=float(result.settled_ts),
                    realized_net_bps=float(result.net_return_bps),
                    realized_cost_bps=float(result.observed_total_cost_bps),
                    fill_status=str(result.status),filled=bool(result.fill_ratio>0),
                    payload={
                        "abstain":False,"direction":direction,"regime":regime,
                        "expected_cost_bps":payload.get("expected_cost_bps"),
                        "expected_net_bps":payload.get("expected_net_bps"),
                        "fill_model":result.fill_model,"fill_ratio":result.fill_ratio,
                        "gross_directional_return_bps":result.gross_directional_return_bps,
                        "data_quality":result.data_quality,"selected":None,
                    },
                )
                settled+=1
            except Exception as exc:
                errors.append(
                    f"{row.get('row_id')}:{type(exc).__name__}:{exc}"
                )

        export=ledger.export_settlements(freeze_id=str(freeze_id))
        return {
            "schema":"hivenance_phase13_settlement_cycle_v1",
            "freeze_id":str(freeze_id),
            "as_of_ts":now_ts,
            "pending_examined":len(pending),
            "settled":settled,
            "abstained":abstained,
            "awaiting":awaiting,
            "no_mature_public_tape":no_tape,
            "errors":errors,
            "total_exported":len(export.get("rows") or []),
            "settlement_book":export,
            "execution_eligible":False,
            "promotion_eligible":False,
        }
    finally:
        market.close()
        ledger.close()
