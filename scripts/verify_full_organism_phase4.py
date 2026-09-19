#!/usr/bin/env python3
"""Verify Phase-4 CoinSelector selection-regret truth on a complete prospective cohort."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.relative_value_lab.selection_regret import ensure_tables,selector_regret_report


def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--settings",type=Path,default=ROOT/"config/settings.yaml")
 ap.add_argument("--profile",type=Path)
 ap.add_argument("--database",type=Path)
 args=ap.parse_args()
 cfg=load_observer_config(args.settings,args.profile)
 db=args.database or Path(str(getattr(cfg,"db_path","data/swarm_data.db")))
 if not db.is_absolute():db=ROOT/db
 store=DataStoreAgent(str(db));ensure_tables(store)
 reasons=[]
 with store._lock:
  runs=store.conn.execute(
   """SELECT f.run_id,
             COUNT(*) AS frozen_n,
             SUM(CASE WHEN f.selected=1 THEN 1 ELSE 0 END) AS selected_n,
             SUM(CASE WHEN f.selected=0 THEN 1 ELSE 0 END) AS rejected_n,
             SUM(CASE WHEN f.selected!=f.blind_selected THEN 1 ELSE 0 END) AS ablation_changed,
             SUM(CASE WHEN s.freeze_id IS NOT NULL THEN 1 ELSE 0 END) AS settled_n,
             MIN(f.target_ts),MAX(f.target_ts)
      FROM full_organism_selector_freezes f
      LEFT JOIN full_organism_selector_settlements_v2 s ON s.freeze_id=f.freeze_id
      GROUP BY f.run_id
      HAVING settled_n=frozen_n AND selected_n>0 AND rejected_n>0
      ORDER BY MAX(f.observed_ts) DESC"""
  ).fetchall()
 if not runs:
  reasons.append("no_complete_selected_and_rejected_cohort")
  chosen=None
 else:
  chosen=runs[0]
 run_id=str(chosen[0]) if chosen else None
 report=selector_regret_report(store,run_id=run_id) if run_id else {}
 if chosen:
  if int(chosen[4] or 0)<=0:reasons.append("coinselector_ablation_did_not_change_selection")
  if int(report.get("settled_n") or 0)!=int(chosen[1] or 0):reasons.append("selector_report_cohort_mismatch")
  if report.get("selected_minus_rejected_bps") is None:reasons.append("selected_rejected_delta_missing")
  if report.get("selector_minus_blind_bps") is None:reasons.append("selector_blind_delta_missing")

 # Prove selected/rejected future observations live in the same universe custody table.
 universe_counts={"selected_future_rows":0,"rejected_future_rows":0}
 if run_id:
  with store._lock:
   fs=store.conn.execute(
    "SELECT symbol,selected,target_ts FROM full_organism_selector_freezes WHERE run_id=?",
    (run_id,),
   ).fetchall()
   for symbol,selected,target in fs:
    n=store.conn.execute(
     """SELECT COUNT(*)
        FROM observation_universe_snapshots u
        JOIN observation_runs r ON r.run_id=u.run_id
        WHERE u.symbol=? AND r.completed_ts>=?""",
     (symbol,float(target or 0)),
    ).fetchone()[0]
    if n:
     key="selected_future_rows" if int(selected or 0)==1 else "rejected_future_rows"
     universe_counts[key]+=1
  if universe_counts["selected_future_rows"]<=0:reasons.append("selected_future_universe_tape_missing")
  if universe_counts["rejected_future_rows"]<=0:reasons.append("rejected_future_universe_tape_missing")

 status="PASS" if not reasons else "REFUSE"
 result={
  "schema":"hivenance_full_organism_phase4_verification_v1",
  "phase":4,"status":status,"run_id":run_id,
  "cohort":{
   "frozen_n":int(chosen[1]) if chosen else 0,
   "selected_n":int(chosen[2]) if chosen else 0,
   "rejected_n":int(chosen[3]) if chosen else 0,
   "coinselector_ablation_changed_n":int(chosen[4]) if chosen else 0,
   "settled_n":int(chosen[5]) if chosen else 0,
   "target_ts_min":float(chosen[6]) if chosen else None,
   "target_ts_max":float(chosen[7]) if chosen else None,
  },
  "universe_custody":universe_counts,
  "selection_regret":report,
  "settlement_schema":"hivenance_selector_opportunity_settlement_v2",
  "settlement_clock":"OBSERVATION_RUN_COMPLETED_TS",
  "reasons":reasons,
  "execution_eligible":False,"promotion_eligible":False,"real_orders_submitted":0,
 }
 print("HIVENANCE_FULL_ORGANISM_PHASE4")
 print(json.dumps(result,indent=2,sort_keys=True,default=str))
 if status=="PASS":
  print("HIVENANCE_FULL_ORGANISM_PHASE4_SELECTION_REGRET_VERIFIED")
  return 0
 return 2

if __name__=="__main__":raise SystemExit(main())
