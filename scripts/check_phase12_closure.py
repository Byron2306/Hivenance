#!/usr/bin/env python3
from __future__ import annotations

import argparse,json
from pathlib import Path

from strategies.relative_value_lab.historical_causal_prosecution import (
    PAIRED_MASKS,ADVERSARIAL_ATTACKS,
)

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--census",type=Path,default=Path("data/full_organism_census.json"))
    ap.add_argument("--out",type=Path,default=Path("data/phase12_closure_status.json"))
    args=ap.parse_args()

    payload=json.loads(args.census.read_text(encoding="utf-8"))
    paired=set(payload.get("paired_masks") or ())
    skipped=set(payload.get("skipped_masks") or ())
    prosecution=((payload.get("historical_prosecution") or {}))
    attack_results=dict(payload.get("adversarial_attacks") or {})

    mandatory_masks=[x for x in PAIRED_MASKS if x!="FULL_HIVE"]
    missing_masks=[x for x in mandatory_masks if x not in paired]
    measured_attacks=[]
    failed_attacks=[]
    for attack_id,row in attack_results.items():
        if not row:
            continue
        status=row.get("status") if isinstance(row,dict) else None
        if status is not None:
            if str(status).upper()=="PASS":
                measured_attacks.append(str(attack_id))
            else:
                failed_attacks.append(str(attack_id))
            continue
        # Quantitative attacks are measured when the replay actually produced
        # a testable-world count, even when no decisions changed.
        if isinstance(row,dict) and "testable_worlds" in row:
            measured_attacks.append(str(attack_id))
    measured_attacks=sorted(set(measured_attacks))
    failed_attacks=sorted(set(failed_attacks))
    missing_attacks=[x for x in ADVERSARIAL_ATTACKS if x not in measured_attacks]

    # A frozen survivor set exists only when every mandatory mask has either
    # paired prosecution or an explicit UNAVAILABLE result in organ_results.
    results=prosecution.get("organ_results") or []
    explicit_unavailable={
        str(row.get("mask_id"))
        for row in results
        if str(row.get("classification"))=="UNAVAILABLE"
    }
    unresolved_masks=[x for x in missing_masks if x not in explicit_unavailable]

    blockers=[]
    if unresolved_masks:
        blockers.append("mandatory_masks_unresolved")
    if missing_attacks:
        blockers.append("adversarial_attacks_unresolved")
    if failed_attacks:
        blockers.append("adversarial_attacks_failed")

    status="PASS" if not blockers else "REFUSE"
    out={
        "schema":"hivenance_phase12_closure_status_v1",
        "status":status,
        "historical_only":True,
        "prospective_usefulness_proved":False,
        "paired_masks":sorted(paired),
        "skipped_masks":sorted(skipped),
        "explicit_unavailable_masks":sorted(explicit_unavailable),
        "unresolved_masks":unresolved_masks,
        "measured_attacks":measured_attacks,
        "missing_attacks":missing_attacks,
        "failed_attacks":failed_attacks,
        "blockers":blockers,
        "survivor_ids":prosecution.get("survivor_ids") or [],
        "execution_eligible":False,
        "promotion_eligible":False,
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(out,indent=2,sort_keys=True),encoding="utf-8")
    print("HIVENANCE_PHASE12_CLOSURE")
    print(json.dumps(out,indent=2,sort_keys=True))
    return 0 if status=="PASS" else 2

if __name__=="__main__":
    raise SystemExit(main())
