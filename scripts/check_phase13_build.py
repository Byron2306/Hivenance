#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from strategies.relative_value_lab.phase13_experiment import (
    PHASE13_REQUIRED_BOOKS,
    PHASE13_REQUIRED_HORIZONS_SECONDS,
)
from strategies.relative_value_lab.phase13_runtime import Phase13Runtime
from strategies.volatility_breakout.models import FeatureVector


def _feature()->FeatureVector:
    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=1_000_000,
        price=100.0,
        realized_volatility_fast=0.01,
        realized_volatility_baseline=0.01,
        volatility_expansion=1.0,
        volume_zscore=0.0,
        trade_count_zscore=0.0,
        order_flow_imbalance=0.0,
        book_imbalance=0.0,
        spread_bps=2.0,
        depth_usd_25bps=100000.0,
        quote_volume_24h=1000000.0,
        return_5=0.001,
        freshness_sec=1.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        values={
            "market_world_state_crystal":{
                "world_state_id":"phase13_build_world",
                "world_state_hash":"sha256:"+"b"*64,
            },
            "regime_inputs":{
                "regime_hint":"phase13_build_fixture",
                "confidence":0.8,
            },
        },
    )


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--freeze",type=Path,default=Path("data/phase13_experiment_freeze.json"))
    ap.add_argument("--census",type=Path,default=Path("data/full_organism_census.json"))
    ap.add_argument("--out",type=Path,default=Path("data/phase13_build_status.json"))
    args=ap.parse_args()

    freeze=json.loads(args.freeze.read_text(encoding="utf-8"))
    blockers=[]

    if freeze.get("schema")!="hivenance_phase13_experiment_freeze_v1":
        blockers.append("freeze_schema_invalid")
    if tuple(freeze.get("books") or ())!=PHASE13_REQUIRED_BOOKS:
        blockers.append("book_roster_not_frozen")
    if tuple(int(x) for x in (freeze.get("horizons_seconds") or ()))!=PHASE13_REQUIRED_HORIZONS_SECONDS:
        blockers.append("horizon_roster_not_frozen")
    if freeze.get("frozen_book_can_change_modes") is not False:
        blockers.append("frozen_book_mutability_violation")
    if freeze.get("adaptive_book_can_change_modes") is not True:
        blockers.append("adaptive_book_mutability_missing")
    if freeze.get("execution_eligible") is not False or freeze.get("promotion_eligible") is not False:
        blockers.append("freeze_authority_escalation")

    synthetic={}
    if not blockers:
        with tempfile.TemporaryDirectory(prefix="hivenance-p13-build-") as td:
            root=Path(td)
            freeze_copy=root/"freeze.json"
            census_copy=root/"census.json"
            ledger_path=root/"books.db"
            freeze_copy.write_text(json.dumps(freeze),encoding="utf-8")
            if args.census.exists():
                census_copy.write_text(args.census.read_text(encoding="utf-8"),encoding="utf-8")
            else:
                census_copy.write_text(json.dumps({"organ_runtime_control":{}}),encoding="utf-8")

            cfg=SimpleNamespace(
                exchange="kraken",
                phase2_worker_signal_federation_enabled=True,
                phase2_worker_coalition_enabled=True,
                medium_trend_phase2_model_enabled=False,
                derivatives_trend_phase2_model_enabled=False,
            )
            runtime=Phase13Runtime(
                cfg,
                freeze_path=freeze_copy,
                census_path=census_copy,
                ledger_path=ledger_path,
            )
            try:
                result=runtime.process_feature(_feature())
                pending=runtime.ledger.pending_forecasts(
                    freeze_id=str(freeze.get("freeze_id") or ""),
                    limit=100000,
                )
                books={str(row.get("book_id") or "") for row in pending}
                worlds={str(row.get("world_state_id") or "") for row in pending}
                hashes={str(row.get("world_state_hash") or "") for row in pending}
                freezes={str(row.get("freeze_id") or "") for row in pending}

                missing_books=[book for book in PHASE13_REQUIRED_BOOKS if book not in books]
                if missing_books:
                    blockers.append("synthetic_book_fanout_incomplete")
                if worlds!={"phase13_build_world"}:
                    blockers.append("synthetic_world_identity_drift")
                if hashes!={"sha256:"+"b"*64}:
                    blockers.append("synthetic_world_hash_drift")
                if freezes!={str(freeze.get("freeze_id") or "")}:
                    blockers.append("synthetic_freeze_identity_drift")

                if pending:
                    first=pending[0]
                    runtime.ledger.persist_settlement(
                        forecast_row_id=first["row_id"],
                        freeze_id=first["freeze_id"],
                        book_id=first["book_id"],
                        world_state_id=first["world_state_id"],
                        world_state_hash=first["world_state_hash"],
                        symbol=first["symbol"],
                        timestamp_ms=first["timestamp_ms"],
                        horizon_seconds=first["horizon_seconds"],
                        model_id=first["model_id"],
                        settled_ts=2000.0,
                        realized_net_bps=1.0,
                        realized_cost_bps=2.0,
                        fill_status="SETTLED",
                        filled=True,
                        payload={"regime":"phase13_build_fixture","abstain":False},
                    )
                    export=runtime.ledger.export_settlements(
                        freeze_id=str(freeze.get("freeze_id") or "")
                    )
                    if len(export.get("rows") or [])!=1:
                        blockers.append("synthetic_settlement_export_failed")
                else:
                    blockers.append("synthetic_forecast_ledger_empty")

                synthetic={
                    "runtime_result":result,
                    "forecast_rows":len(pending),
                    "books":sorted(books),
                    "worlds":sorted(worlds),
                    "freeze_ids":sorted(freezes),
                }
            finally:
                runtime.close()

    payload={
        "schema":"hivenance_phase13_build_status_v1",
        "status":"PASS" if not blockers else "REFUSE",
        "freeze_id":freeze.get("freeze_id"),
        "blockers":blockers,
        "synthetic_same_world_test":synthetic,
        "forecast_creation_separate_from_settlement":True,
        "settlement_source":"public_observation_snapshots",
        "execution_eligible":False,
        "promotion_eligible":False,
        "prospective_usefulness_proved":False,
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    print("HIVENANCE_PHASE13_BUILD_STATUS")
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0 if not blockers else 2


if __name__=="__main__":
    raise SystemExit(main())
