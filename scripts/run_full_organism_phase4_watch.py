#!/usr/bin/env python3
"""Phase-4 frozen-cohort prospective watch.

Creates at most one fresh selector cohort, then follows that exact frozen symbol
set with public market data until the 5-minute target is settleable. No reranking
may substitute new symbols into the cohort.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import build_public_client,load_observer_config
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent
from strategies.relative_value_lab.selection_regret import (
    FROZEN_FOLLOW_PROTOCOL,
    collect_frozen_selector_follow_tape,
    settle_selector_follow_cohort,
    selector_regret_report_v3,
)


class StoreBridge:
    def __init__(self,store:DataStoreAgent)->None:self.store=store
    def share_data(self,_key:str,event:dict[str,Any])->None:self.store.handle_event(event)


def _latest_follow_cohort(store:DataStoreAgent)->str|None:
    with store._lock:
        rows=store.conn.execute(
            "SELECT run_id,payload FROM full_organism_selector_freezes ORDER BY observed_ts DESC"
        ).fetchall()
    for run_id,raw in rows:
        try:p=json.loads(raw or "{}")
        except Exception:continue
        if str(p.get("maturation_protocol") or "")==FROZEN_FOLLOW_PROTOCOL:
            return str(run_id)
    return None


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--settings",type=Path,default=ROOT/"config/settings.yaml")
    ap.add_argument("--profile",type=Path)
    ap.add_argument("--database",type=Path)
    ap.add_argument("--minutes",type=float,default=7.0)
    ap.add_argument("--pause-sec",type=float,default=45.0)
    ap.add_argument("--mature-only",action="store_true",
                    help="Resume the latest frozen-follow cohort without creating a new one.")
    args=ap.parse_args()

    cfg=load_observer_config(args.settings,args.profile)
    cfg.live_mode=False
    cfg.dry_run=True
    db=args.database or Path(str(getattr(cfg,"db_path","data/swarm_data.db")))
    if not db.is_absolute():db=ROOT/db
    store=DataStoreAgent(str(db))
    bridge=StoreBridge(store)
    client=build_public_client(str(getattr(cfg,"exchange","kraken") or "kraken").lower())

    cohort_run_id=None
    cohort_freeze=None
    if args.mature_only:
        cohort_run_id=_latest_follow_cohort(store)
        if not cohort_run_id:
            raise SystemExit("PHASE4_REFUSE no frozen-follow cohort exists; run once without --mature-only")
    else:
        cfg.full_organism_selector_freeze_enabled=True
        cfg.full_organism_selector_maturation_protocol=FROZEN_FOLLOW_PROTOCOL
        observer=ObservationSwarmAgent(cfg,client,coordinator=bridge)
        obs=observer.run_once()
        cohort_run_id=str(((obs.get("run") or {}).get("run_id") if isinstance(obs,dict) else "") or "")
        cohort_freeze=obs.get("selector_freeze") if isinstance(obs,dict) else None
        if not cohort_run_id or not isinstance(cohort_freeze,dict):
            raise SystemExit("PHASE4_REFUSE fresh cohort freeze failed")
        if str(cohort_freeze.get("maturation_protocol") or "")!=FROZEN_FOLLOW_PROTOCOL:
            raise SystemExit("PHASE4_REFUSE fresh cohort protocol mismatch")

    stop=False
    def _stop(_sig,_frame):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGINT,_stop);signal.signal(signal.SIGTERM,_stop)

    deadline=time.monotonic()+max(30.0,float(args.minutes)*60.0)
    cycle=0
    last={}
    while not stop and time.monotonic()<deadline:
        cycle+=1
        now=time.time()
        follow=collect_frozen_selector_follow_tape(
            store=store,client=client,cohort_run_id=str(cohort_run_id),now_ts=now,
            orderbook_depth=max(5,min(500,int(getattr(cfg,"phase1_observation_orderbook_depth",50) or 50))),
        )
        settlement=settle_selector_follow_cohort(
            store=store,cohort_run_id=str(cohort_run_id),now_ts=time.time(),
            tolerance_sec=float(getattr(cfg,"full_organism_selector_settlement_tolerance_sec",120.0) or 120.0),
        )
        report=selector_regret_report_v3(store,run_id=str(cohort_run_id))
        last={
            "cycle":cycle,
            "mode":"MATURATION_ONLY" if args.mature_only else "FRESH_COHORT_EXACT_FOLLOW",
            "cohort_run_id":cohort_run_id,
            "selector_freeze":cohort_freeze if cycle==1 else None,
            "follow":follow,
            "settlement":settlement,
            "settled_n":report.get("settled_n"),
            "selected_n":report.get("selected_n"),
            "rejected_n":report.get("rejected_n"),
            "selected_minus_rejected_bps":report.get("selected_minus_rejected_bps"),
            "selector_minus_blind_bps":report.get("selector_minus_blind_bps"),
            "execution_eligible":False,
            "promotion_eligible":False,
            "real_orders_submitted":0,
        }
        print("[PHASE4]",json.dumps(last,sort_keys=True,default=str))
        if settlement.get("examined") and int(settlement.get("deferred") or 0)==0:
            break
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        wait=min(max(5.0,float(args.pause_sec)),remaining)
        until=time.monotonic()+wait
        while not stop and time.monotonic()<until:
            time.sleep(min(.5,until-time.monotonic()))

    print("HIVENANCE_FULL_ORGANISM_PHASE4_WATCH_RESULT")
    print(json.dumps(last,indent=2,sort_keys=True,default=str))
    return 0


if __name__=="__main__":raise SystemExit(main())
