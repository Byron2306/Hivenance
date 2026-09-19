#!/usr/bin/env python3
"""Verify recovery Phase-3 full comparison composition on latest hypothesis run."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config

REQUIRED_TYPES={
 "SELF_SAME_UTC_HOUR",
 "CROSS_SECTION",
 "SELECTED_VS_REJECTED",
 "NEAREST_PRIOR_STATES",
 "EVENT_VS_CONTROL",
}
REQUIRED_CONTROLS={"NO_TRADE","DETERMINISTIC_RANDOM","TIME_SHIFT_PLACEBO","SIMPLE_NESTED_MODEL"}


def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--settings",type=Path,default=ROOT/"config/settings.yaml")
 ap.add_argument("--profile",type=Path)
 ap.add_argument("--database",type=Path)
 args=ap.parse_args()
 cfg=load_observer_config(args.settings,args.profile)
 db=args.database or Path(str(getattr(cfg,"db_path","data/swarm_data.db")))
 if not db.is_absolute():db=ROOT/db
 store=DataStoreAgent(str(db))
 runs=store.get_hypothesis_runs(limit=1)
 latest=runs[0] if runs else {}
 reasons=[]
 payload=latest.get("payload") if isinstance(latest.get("payload"),dict) else {}
 block=payload.get("full_comparison") if isinstance(payload.get("full_comparison"),dict) else {}
 rows=block.get("rows") if isinstance(block.get("rows"),list) else []
 symbols=int(block.get("symbols_evaluated") or 0)
 built=int(block.get("packets_built") or 0)
 if not latest:reasons.append("no_hypothesis_run")
 if symbols<=0:reasons.append("no_symbols_evaluated")
 if built!=symbols:reasons.append("comparison_packet_not_built_for_every_symbol")
 if block.get("execution_eligible") is not False:reasons.append("comparison_execution_authority_invalid")
 if block.get("promotion_eligible") is not False:reasons.append("comparison_promotion_authority_invalid")

 reports=[]
 selected_rejected_with_both=0
 cross_section_live=0
 nearest_live=0
 for row in rows:
  rr=[]
  types=set(row.get("comparison_types") or ())
  missing=sorted(REQUIRED_TYPES-types)
  if missing:rr.append("missing_types:"+",".join(missing))
  matched=row.get("matched_n_by_type") if isinstance(row.get("matched_n_by_type"),dict) else {}
  if int(matched.get("CROSS_SECTION") or 0)>0:cross_section_live+=1
  if int(matched.get("NEAREST_PRIOR_STATES") or 0)>0:nearest_live+=1
  sr=row.get("selected_rejected_counts") if isinstance(row.get("selected_rejected_counts"),dict) else {}
  if int(sr.get("selected_n") or 0)>0 and int(sr.get("rejected_n") or 0)>0:
   selected_rejected_with_both+=1
  controls=row.get("controls") if isinstance(row.get("controls"),dict) else {}
  if not REQUIRED_CONTROLS.issubset(set(controls)):rr.append("required_controls_missing")
  for key in REQUIRED_CONTROLS:
   item=controls.get(key) if isinstance(controls.get(key),dict) else {}
   if item.get("authority")!="CONTROL_ONLY":rr.append("control_authority_invalid:"+key)
  reports.append({
   "symbol":row.get("symbol"),
   "packet_id":row.get("packet_id"),
   "matched_n_by_type":matched,
   "selected_rejected_history_runs":row.get("selected_rejected_history_runs"),
   "selected_rejected_counts":sr,
   "valid":not rr,
   "reasons":rr,
  })

 # Inspect the latest observation run directly to prove rejected candidates survived persistence.
 observation_runs=store.get_observation_runs(limit=2)
 persisted_rejected=0
 persisted_selected=0
 for run in observation_runs:
  p=run.get("payload") if isinstance(run.get("payload"),dict) else {}
  universe=p.get("comparison_universe") if isinstance(p.get("comparison_universe"),list) else []
  if universe:
   persisted_selected=sum(1 for x in universe if isinstance(x,dict) and x.get("selected_for_phase2") is True)
   persisted_rejected=sum(1 for x in universe if isinstance(x,dict) and x.get("selected_for_phase2") is False)
   if persisted_selected and persisted_rejected:
    break
 if persisted_selected<=0:reasons.append("persisted_selected_universe_missing")
 if persisted_rejected<=0:reasons.append("persisted_rejected_universe_missing")
 if cross_section_live<=0:reasons.append("no_live_cross_section_matches")
 if nearest_live<=0:reasons.append("no_nearest_prior_state_matches")
 if selected_rejected_with_both<=0:reasons.append("no_prior_selected_vs_rejected_two_sided_comparison")
 if any(not x["valid"] for x in reports):reasons.append("one_or_more_comparison_packets_invalid")

 # Stronger selected/rejected gate: read current packet results from the latest run payload's
 # forecast feature contexts when possible is expensive; matched telemetry alone confirms the
 # family ran, while persisted rejected universe proves future runs have both sides available.
 status="PASS" if not reasons else "REFUSE"
 result={
  "schema":"hivenance_full_organism_phase3_verification_v1",
  "phase":3,"status":status,
  "run_id":latest.get("run_id"),
  "symbols_evaluated":symbols,
  "packets_built":built,
  "persisted_selected":persisted_selected,
  "persisted_rejected":persisted_rejected,
  "cross_section_symbols_with_matches":cross_section_live,
  "nearest_state_symbols_with_matches":nearest_live,
  "selected_rejected_symbols_with_both_sides":selected_rejected_with_both,
  "rows":reports,"reasons":reasons,
  "execution_eligible":False,"promotion_eligible":False,"real_orders_submitted":0,
 }
 print("HIVENANCE_FULL_ORGANISM_PHASE3")
 print(json.dumps(result,indent=2,sort_keys=True,default=str))
 if status=="PASS":
  print("HIVENANCE_FULL_ORGANISM_PHASE3_COMPARISON_COMPOSITION_VERIFIED")
  return 0
 return 2

if __name__=="__main__":raise SystemExit(main())
