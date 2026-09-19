#!/usr/bin/env python3
"""Verify Phase-4 CoinSelector truth using the exact frozen-follow protocol."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.relative_value_lab.selection_regret import (
    ensure_tables,FROZEN_FOLLOW_PROTOCOL,selector_regret_report_v3,
)


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
        freeze_rows=store.conn.execute(
            "SELECT run_id,payload FROM full_organism_selector_freezes ORDER BY observed_ts DESC"
        ).fetchall()
    run_id=None
    for rid,raw in freeze_rows:
        try:p=json.loads(raw or "{}")
        except Exception:continue
        if str(p.get("maturation_protocol") or "")==FROZEN_FOLLOW_PROTOCOL:
            run_id=str(rid);break
    if not run_id:
        reasons.append("no_frozen_follow_cohort")

    chosen=None
    if run_id:
        with store._lock:
            chosen=store.conn.execute(
                """SELECT COUNT(*) AS frozen_n,
                          SUM(CASE WHEN selected=1 THEN 1 ELSE 0 END) AS selected_n,
                          SUM(CASE WHEN selected=0 THEN 1 ELSE 0 END) AS rejected_n,
                          SUM(CASE WHEN selected!=blind_selected THEN 1 ELSE 0 END) AS ablation_changed,
                          MIN(target_ts),MAX(target_ts)
                   FROM full_organism_selector_freezes WHERE run_id=?""",
                (run_id,),
            ).fetchone()
            settled_n=store.conn.execute(
                """SELECT COUNT(*) FROM full_organism_selector_settlements_v3 s
                   JOIN full_organism_selector_freezes f ON f.freeze_id=s.freeze_id
                   WHERE f.run_id=?""",(run_id,)
            ).fetchone()[0]
            follow_symbols=store.conn.execute(
                """SELECT COUNT(DISTINCT symbol) FROM full_organism_selector_follow_snapshots
                   WHERE cohort_run_id=?""",(run_id,)
            ).fetchone()[0]
        frozen_n=int(chosen[0] or 0)
        selected_n=int(chosen[1] or 0)
        rejected_n=int(chosen[2] or 0)
        ablation_changed=int(chosen[3] or 0)
        if frozen_n<=0:reasons.append("frozen_cohort_empty")
        if selected_n<=0 or rejected_n<=0:reasons.append("selected_or_rejected_side_missing")
        if ablation_changed<=0:reasons.append("coinselector_ablation_did_not_change_selection")
        if int(settled_n)!=frozen_n:reasons.append("frozen_follow_cohort_not_fully_settled")
        if int(follow_symbols)!=frozen_n:reasons.append("not_every_frozen_symbol_has_follow_tape")
    else:
        frozen_n=selected_n=rejected_n=ablation_changed=settled_n=follow_symbols=0

    report=selector_regret_report_v3(store,run_id=run_id) if run_id else {}
    if run_id:
        if int(report.get("settled_n") or 0)!=frozen_n:reasons.append("selector_report_cohort_mismatch")
        if report.get("selected_minus_rejected_bps") is None:reasons.append("selected_rejected_delta_missing")
        if report.get("selector_minus_blind_bps") is None:reasons.append("selector_blind_delta_missing")

    status="PASS" if not reasons else "REFUSE"
    result={
        "schema":"hivenance_full_organism_phase4_verification_v2",
        "phase":4,"status":status,"run_id":run_id,
        "maturation_protocol":FROZEN_FOLLOW_PROTOCOL,
        "cohort":{
            "frozen_n":frozen_n,
            "selected_n":selected_n,
            "rejected_n":rejected_n,
            "coinselector_ablation_changed_n":ablation_changed,
            "settled_n":int(settled_n),
            "follow_symbols":int(follow_symbols),
            "target_ts_min":float(chosen[4]) if chosen and chosen[4] is not None else None,
            "target_ts_max":float(chosen[5]) if chosen and chosen[5] is not None else None,
        },
        "selection_regret":report,
        "settlement_schema":"hivenance_selector_opportunity_settlement_v3",
        "settlement_clock":"FROZEN_COHORT_FOLLOW_CUSTODY_TS",
        "legacy_v1_v2_evidence_status":"SUPERSEDED_FOR_PHASE4_GATE_ONLY_NOT_DELETED",
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
