#!/usr/bin/env python3
"""Focused Phase-4 public-market maturation watch.

Repeatedly observes the full ranked universe and settles mature CoinSelector
freezes. Research only. No private endpoints or order transmission.
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
    settle_mature_selector_freezes,selector_regret_report,
)


class StoreBridge:
    def __init__(self,store:DataStoreAgent)->None:self.store=store
    def share_data(self,_key:str,event:dict[str,Any])->None:self.store.handle_event(event)


def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--settings",type=Path,default=ROOT/"config/settings.yaml")
 ap.add_argument("--profile",type=Path)
 ap.add_argument("--database",type=Path)
 ap.add_argument("--minutes",type=float,default=7.0)
 ap.add_argument("--pause-sec",type=float,default=45.0)
 ap.add_argument("--mature-only",action="store_true",
                 help="Collect future public tape and settle existing freezes without creating new selector cohorts.")
 args=ap.parse_args()

 cfg=load_observer_config(args.settings,args.profile)
 cfg.live_mode=False
 cfg.dry_run=True
 if args.mature_only:
  cfg.full_organism_selector_freeze_enabled=False
 db=args.database or Path(str(getattr(cfg,"db_path","data/swarm_data.db")))
 if not db.is_absolute():db=ROOT/db
 store=DataStoreAgent(str(db))
 bridge=StoreBridge(store)
 client=build_public_client(str(getattr(cfg,"exchange","kraken") or "kraken").lower())
 observer=ObservationSwarmAgent(cfg,client,coordinator=bridge)

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
  obs=observer.run_once()
  settlement=settle_mature_selector_freezes(
   store=store,now_ts=time.time(),
   tolerance_sec=float(getattr(cfg,"full_organism_selector_settlement_tolerance_sec",180.0) or 180.0),
   limit=max(1,int(getattr(cfg,"full_organism_selector_settlement_batch_limit",2000) or 2000)),
  )
  report=selector_regret_report(store)
  last={
   "cycle":cycle,
   "mode":"MATURATION_ONLY" if args.mature_only else "FREEZE_AND_MATURE",
   "observation_run_id":((obs.get("run") or {}).get("run_id") if isinstance(obs,dict) else None),
   "selector_freeze":(obs.get("selector_freeze") if isinstance(obs,dict) else None),
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
