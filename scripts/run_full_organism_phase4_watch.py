#!/usr/bin/env python3
"""Phase-4 frozen-cohort CoinSelector maturation watch.

Creates exactly one prospective ranked cohort, then follows those exact symbols
until the frozen horizon matures. No reranking, substitution, private endpoints,
orders, execution authority, or promotion authority.
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
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

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
    def __init__(self,store:DataStoreAgent)->None:
        self.store=store
    def share_data(self,_key:str,event:dict[str,Any])->None:
        self.store.handle_event(event)


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--settings",type=Path,default=ROOT/"config/settings.yaml")
    ap.add_argument("--profile",type=Path)
    ap.add_argument("--database",type=Path)
    ap.add_argument("--minutes",type=float,default=8.0)
    ap.add_argument("--pause-sec",type=float,default=45.0)
    ap.add_argument("--follow-tolerance-sec",type=float,default=120.0)
    args=ap.parse_args()

    cfg=load_observer_config(args.settings,args.profile)
    cfg.live_mode=False
    cfg.dry_run=True
    cfg.full_organism_selector_maturation_protocol=FROZEN_FOLLOW_PROTOCOL
    cfg.full_organism_selector_freeze_enabled=True

    db=args.database or Path(str(getattr(cfg,"db_path","data/swarm_data.db")))
    if not db.is_absolute():
        db=ROOT/db
    store=DataStoreAgent(str(db))
    bridge=StoreBridge(store)
    client=build_public_client(str(getattr(cfg,"exchange","kraken") or "kraken").lower())
    observer=ObservationSwarmAgent(cfg,client,coordinator=bridge)

    # Freeze ONE cohort before any future follow observations.
    obs=observer.run_once()
    cohort_run_id=str(((obs.get("run") or {}).get("run_id") if isinstance(obs,dict) else "") or "")
    freeze_summary=obs.get("selector_freeze") if isinstance(obs,dict) else None
    if not cohort_run_id or not isinstance(freeze_summary,dict):
        print("HIVENANCE_FULL_ORGANISM_PHASE4_WATCH_RESULT")
        print(json.dumps({
            "status":"REFUSE",
            "reason":"frozen_cohort_creation_failed",
            "observation_run_id":cohort_run_id or None,
            "selector_freeze":freeze_summary,
            "execution_eligible":False,
            "promotion_eligible":False,
            "real_orders_submitted":0,
        },indent=2,sort_keys=True,default=str))
        return 2
    if str(freeze_summary.get("maturation_protocol") or "")!=FROZEN_FOLLOW_PROTOCOL:
        raise SystemExit("PHASE4_REFUSE wrong maturation protocol")

    # Prevent this watcher from creating any later cohorts.
    cfg.full_organism_selector_freeze_enabled=False

    stop=False
    def _stop(_sig,_frame):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGINT,_stop)
    signal.signal(signal.SIGTERM,_stop)

    deadline=time.monotonic()+max(30.0,float(args.minutes)*60.0)
    cycle=0
    last={}
    while not stop and time.monotonic()<deadline:
        cycle+=1
        follow=collect_frozen_selector_follow_tape(
            store=store,
            client=client,
            cohort_run_id=cohort_run_id,
            now_ts=time.time(),
        )
        settlement=settle_selector_follow_cohort(
            store=store,
            cohort_run_id=cohort_run_id,
            now_ts=time.time(),
            tolerance_sec=max(1.0,float(args.follow_tolerance_sec)),
        )
        report=selector_regret_report_v3(store,run_id=cohort_run_id)
        last={
            "schema":"hivenance_full_organism_phase4_frozen_follow_watch_v1",
            "status":"RUNNING",
            "cycle":cycle,
            "cohort_run_id":cohort_run_id,
            "selector_freeze":freeze_summary,
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
        print("[PHASE4-FROZEN]",json.dumps(last,sort_keys=True,default=str))

        if int(report.get("settled_n") or 0)>=int(freeze_summary.get("universe_n") or 0)>0:
            last["status"]="COMPLETE"
            break

        remaining=deadline-time.monotonic()
        if remaining<=0:
            break
        wait=min(max(5.0,float(args.pause_sec)),remaining)
        until=time.monotonic()+wait
        while not stop and time.monotonic()<until:
            time.sleep(min(.5,until-time.monotonic()))

    print("HIVENANCE_FULL_ORGANISM_PHASE4_WATCH_RESULT")
    print(json.dumps(last,indent=2,sort_keys=True,default=str))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
