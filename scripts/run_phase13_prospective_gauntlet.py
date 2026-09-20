#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

if os.environ.get("PREFIX") and not os.environ.get("HIVENANCE_PHASE13_PRELOAD_DONE"):
    libpython=Path(os.environ["PREFIX"])/"lib"/f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
    if libpython.exists():
        env=dict(os.environ)
        existing=env.get("LD_PRELOAD","").strip()
        env["LD_PRELOAD"]=str(libpython) if not existing else str(libpython)+":"+existing
        env["HIVENANCE_PHASE13_PRELOAD_DONE"]="1"
        os.execve(sys.executable,[sys.executable,*sys.argv],env)

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from agents.coordinator import SwarmCoordinator
from agents.kraken_public_client import KrakenPublicClient
from main import apply_phase0_safety_policy,load_config
from strategies.relative_value_lab.phase13_book_ledger import Phase13BookLedger
from strategies.relative_value_lab.phase13_settlement_runtime import settle_mature_phase13_books

STOP=False

def _stop(_sig:int,_frame:Any)->None:
    global STOP
    STOP=True

def _sha_file(path:Path)->str:
    return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()

def _stop_agents(coordinator:SwarmCoordinator)->None:
    for agent in list(getattr(coordinator,"agents",{}).values()):
        stop=getattr(agent,"stop",None)
        if not callable(stop):
            continue
        try:
            stop()
        except TypeError:
            try:stop(timeout=1)
            except Exception:pass
        except Exception:
            pass
    coordinator.running=False

def main()->int:
    ap=argparse.ArgumentParser(description="Hivenance Phase-13 prospective frozen + adaptive gauntlet")
    duration=ap.add_mutually_exclusive_group()
    duration.add_argument("--hours",type=float)
    duration.add_argument("--continuous",action="store_true")
    ap.add_argument("--pause-sec",type=float,default=30.0)
    ap.add_argument("--freeze",type=Path,default=ROOT/"data"/"phase13_experiment_freeze.json")
    ap.add_argument("--census",type=Path,default=ROOT/"data"/"full_organism_census.json")
    ap.add_argument("--ledger",type=Path,default=ROOT/"data"/"hivenance_phase13_books.db")
    ap.add_argument("--market-db",type=Path,default=ROOT/"data"/"swarm_data.db")
    ap.add_argument("--settlement-out",type=Path,default=ROOT/"data"/"phase13_settlement_book.json")
    ap.add_argument("--receipt",type=Path,default=ROOT/"data"/"phase13_gauntlet_latest.json")
    ap.add_argument("--quiet-kraken",action="store_true")
    args=ap.parse_args()

    hours=6.0 if args.hours is None and not args.continuous else args.hours
    if hours is not None and hours<=0:
        ap.error("--hours must be >0")

    freeze=json.loads(args.freeze.read_text(encoding="utf-8"))
    freeze_id=str(freeze.get("freeze_id") or "")
    if not freeze_id:
        raise ValueError("phase13_freeze_id_missing")
    freeze_file_digest=_sha_file(args.freeze)

    signal.signal(signal.SIGINT,_stop)
    signal.signal(signal.SIGTERM,_stop)

    cfg=apply_phase0_safety_policy(load_config())
    cfg.live_mode=False
    cfg.dry_run=True
    cfg.phase5_shadow_enabled=True
    cfg.phase6_canary_enabled=False
    cfg.phase6_live_submission_enabled=False
    cfg.phase7_growth_enabled=False
    cfg.phase7_stage_activation_enabled=False
    cfg.kraken_api_key=""
    cfg.kraken_api_secret=""
    cfg.binance_api_key=""
    cfg.binance_api_secret=""
    cfg.phase13_prospective_enabled=True
    cfg.phase13_freeze_path=str(args.freeze)
    cfg.phase13_census_path=str(args.census)
    cfg.phase13_ledger_path=str(args.ledger)
    cfg.phase2_horizons_seconds=list(freeze.get("horizons_seconds") or [300,900,3600,14400,86400])

    client=KrakenPublicClient(progress=not args.quiet_kraken) if str(cfg.exchange).lower()=="kraken" else None
    coordinator=SwarmCoordinator(cfg)
    coordinator.initialize(client)
    shadow=coordinator.agents.get("shadow_flight")
    if shadow is None:
        raise RuntimeError("phase13_shadow_driver_unavailable")

    started_wall=time.time()
    started_mono=time.monotonic()
    deadline=None if args.continuous else started_mono+float(hours)*3600.0
    cycles=0
    errors=[]
    recent=[]
    last_settlement={}
    try:
        print("HIVENANCE_PHASE13_PROSPECTIVE_GAUNTLET")
        print("freeze_id=",freeze_id)
        print("freeze_file_digest=",freeze_file_digest)
        print("frozen_book_mutable=False")
        print("adaptive_book_mutable=True")
        print("execution_eligible=False")
        print("promotion_eligible=False")
        print("real_orders_submitted=0",flush=True)

        while not STOP and (deadline is None or time.monotonic()<deadline):
            cycles+=1
            cycle_started=time.monotonic()
            try:
                if _sha_file(args.freeze)!=freeze_file_digest:
                    raise RuntimeError("phase13_freeze_file_mutated")

                payload=shadow.run_once(drive_upstream=True)
                phase2=((payload.get("upstream_cycle") or {}).get("phase2_cycle") or {})
                phase13=phase2.get("phase13") if isinstance(phase2,dict) else {}
                last_settlement=settle_mature_phase13_books(
                    freeze_id=freeze_id,
                    ledger_path=args.ledger,
                    market_db_path=args.market_db,
                    as_of_ts=time.time(),
                )
                book=last_settlement.get("settlement_book") or {}
                args.settlement_out.parent.mkdir(parents=True,exist_ok=True)
                args.settlement_out.write_text(json.dumps(book,indent=2,sort_keys=True),encoding="utf-8")

                ledger=Phase13BookLedger(args.ledger)
                try:
                    counts=ledger.counts(freeze_id=freeze_id)
                finally:
                    ledger.close()

                summary={
                    "cycle":cycles,
                    "runtime_sec":round(time.monotonic()-cycle_started,3),
                    "phase13_features_processed":int((phase13 or {}).get("features_processed") or 0),
                    "phase13_book_rows_inserted":int((phase13 or {}).get("book_rows_inserted") or 0),
                    "phase13_errors":int((phase13 or {}).get("errors") or 0),
                    "forecasts_total":counts["forecasts"],
                    "settlements_total":counts["settlements"],
                    "worlds_total":counts["worlds"],
                    "books_total":counts["books"],
                    "settled_this_cycle":int(last_settlement.get("settled") or 0),
                    "settlement_errors":len(last_settlement.get("errors") or []),
                }
                recent.append(summary)
                recent=recent[-500:]
                print(
                    "[P13] "
                    f"cycle={cycles} "
                    f"worlds={summary['worlds_total']} "
                    f"forecasts={summary['forecasts_total']} "
                    f"settlements={summary['settlements_total']} "
                    f"new_rows={summary['phase13_book_rows_inserted']} "
                    f"settled={summary['settled_this_cycle']} "
                    f"errors={summary['phase13_errors']+summary['settlement_errors']}",
                    flush=True,
                )
            except Exception as exc:
                msg=f"cycle_{cycles}:{type(exc).__name__}:{exc}"
                errors.append(msg)
                print("[P13] ERROR "+msg,flush=True)
                if "phase13_freeze_file_mutated" in msg:
                    break

            if STOP or (deadline is not None and time.monotonic()>=deadline):
                break
            until=time.monotonic()+max(0.0,float(args.pause_sec))
            while not STOP and time.monotonic()<until:
                time.sleep(min(.5,until-time.monotonic()))

        try:
            last_settlement=settle_mature_phase13_books(
                freeze_id=freeze_id,
                ledger_path=args.ledger,
                market_db_path=args.market_db,
                as_of_ts=time.time(),
            )
            book=last_settlement.get("settlement_book") or {}
            args.settlement_out.write_text(json.dumps(book,indent=2,sort_keys=True),encoding="utf-8")
        except Exception as exc:
            errors.append(f"final_settlement:{type(exc).__name__}:{exc}")

        ledger=Phase13BookLedger(args.ledger)
        try:
            counts=ledger.counts(freeze_id=freeze_id)
        finally:
            ledger.close()

        receipt={
            "schema":"hivenance_phase13_prospective_gauntlet_receipt_v1",
            "freeze_id":freeze_id,
            "freeze_file_digest":freeze_file_digest,
            "started_ts":started_wall,
            "ended_ts":time.time(),
            "wall_clock_seconds":round(time.monotonic()-started_mono,3),
            "cycles_completed":cycles,
            "continuous_requested":bool(args.continuous),
            "requested_hours":None if args.continuous else float(hours),
            "interrupted":bool(STOP),
            "ledger_counts":counts,
            "last_settlement_summary":{
                k:v for k,v in last_settlement.items() if k!="settlement_book"
            },
            "recent_cycles":recent,
            "errors":errors,
            "frozen_book_can_change_modes":False,
            "adaptive_book_can_change_modes":True,
            "execution_eligible":False,
            "promotion_eligible":False,
            "private_exchange_access":False,
            "real_orders_submitted":0,
        }
        args.receipt.parent.mkdir(parents=True,exist_ok=True)
        args.receipt.write_text(json.dumps(receipt,indent=2,sort_keys=True),encoding="utf-8")
        print("HIVENANCE_PHASE13_PROSPECTIVE_GAUNTLET_RESULT")
        print(json.dumps(receipt,indent=2,sort_keys=True),flush=True)
        return 0 if not errors else 2
    finally:
        _stop_agents(coordinator)

if __name__=="__main__":
    raise SystemExit(main())
