#!/usr/bin/env python3
"""Verify Phase-2 full temporal lattice on the latest Phase-2 run."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config


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
    reasons=[]
    latest=runs[0] if runs else {}
    if not latest:reasons.append("no_hypothesis_run")
    payload=latest.get("payload") if isinstance(latest.get("payload"),dict) else {}
    temporal=payload.get("temporal_lattice") if isinstance(payload.get("temporal_lattice"),dict) else {}
    rows=temporal.get("rows") if isinstance(temporal.get("rows"),list) else []
    symbols=int(temporal.get("symbols_evaluated") or 0)
    built=int(temporal.get("lattices_built") or 0)
    if symbols<=0:reasons.append("no_symbols_evaluated")
    if built!=symbols:reasons.append("temporal_lattice_not_built_for_every_symbol")
    if temporal.get("execution_eligible") is not False:reasons.append("temporal_execution_authority_invalid")
    if temporal.get("promotion_eligible") is not False:reasons.append("temporal_promotion_authority_invalid")

    row_reports=[]
    for row in rows:
        rr=[]
        lineage=row.get("lineage_groups") if isinstance(row.get("lineage_groups"),dict) else {}
        price_lineage=lineage.get("PUBLIC_PRICE_HISTORY") if isinstance(lineage.get("PUBLIC_PRICE_HISTORY"),dict) else {}
        if int(price_lineage.get("independent_evidence_roots") or 0)>1:
            rr.append("price_transforms_fake_independence")
        present=row.get("present") if isinstance(row.get("present"),dict) else {}
        if "macro" not in present or "oracle" not in present:
            rr.append("temporal_group_telemetry_missing")
        if not row.get("canonical_world_state_id") or not row.get("canonical_world_state_hash"):
            rr.append("canonical_world_binding_missing")
        if not isinstance(row.get("conflict"),dict):
            rr.append("conflict_map_missing")
        row_reports.append({
            "symbol":row.get("symbol"),
            "lattice_id":row.get("lattice_id"),
            "canonical_world_state_id":row.get("canonical_world_state_id"),
            "present":present,
            "conflict":row.get("conflict"),
            "valid":not rr,
            "reasons":rr,
        })
    if any(not r["valid"] for r in row_reports):reasons.append("one_or_more_temporal_lattices_invalid")

    status="PASS" if not reasons else "REFUSE"
    result={
        "schema":"hivenance_full_organism_phase2_verification_v1",
        "phase":2,
        "status":status,
        "run_id":latest.get("run_id"),
        "symbols_evaluated":symbols,
        "lattices_built":built,
        "rows":row_reports,
        "reasons":reasons,
        "execution_eligible":False,
        "promotion_eligible":False,
        "real_orders_submitted":0,
    }
    print("HIVENANCE_FULL_ORGANISM_PHASE2")
    print(json.dumps(result,indent=2,sort_keys=True,default=str))
    if status=="PASS":
        print("HIVENANCE_FULL_ORGANISM_PHASE2_TEMPORAL_LATTICE_VERIFIED")
        return 0
    return 2


if __name__=="__main__":
    raise SystemExit(main())
