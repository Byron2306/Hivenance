#!/usr/bin/env python3
from __future__ import annotations

import argparse,json
from pathlib import Path
from collections import defaultdict

from strategies.relative_value_lab.phase14_scientific_gate import (
    summarize_book,validate_phase14_input,
)

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--freeze",type=Path,default=Path("data/phase13_experiment_freeze.json"))
    ap.add_argument("--settlements",type=Path,default=Path("data/phase13_settlement_book.json"))
    ap.add_argument("--out",type=Path,default=Path("data/phase14_scientific_gate.json"))
    args=ap.parse_args()

    freeze=json.loads(args.freeze.read_text(encoding="utf-8"))
    settlements=json.loads(args.settlements.read_text(encoding="utf-8"))
    rows=list(settlements.get("rows") or [])
    validate_phase14_input(
        expected_freeze_id=str(freeze.get("freeze_id") or ""),
        receipt_freeze_ids=[str(row.get("freeze_id") or "") for row in rows],
    )

    by_book=defaultdict(list)
    for row in rows:
        by_book[str(row.get("book_id") or "")].append(row)

    results={}
    for book_id in freeze.get("books") or []:
        book_rows=by_book.get(str(book_id),[])
        result=summarize_book(
            book_id=str(book_id),
            realized_net_bps=[
                float(r["realized_net_bps"])
                for r in book_rows
                if r.get("realized_net_bps") is not None
            ],
            world_ids=[str(r.get("world_state_id") or "") for r in book_rows],
            minimum_samples=int(freeze.get("minimum_samples") or 30),
            minimum_distinct_market_worlds=int(freeze.get("minimum_distinct_market_worlds") or 20),
        )
        results[str(book_id)]=result.to_dict()

    primary=results.get("FULL_HIVE_FROZEN") or {}
    sufficient=(
        int(primary.get("settled_n") or 0)>=int(freeze.get("minimum_samples") or 30)
        and int(primary.get("distinct_worlds") or 0)>=int(freeze.get("minimum_distinct_market_worlds") or 20)
    )
    payload={
        "schema":"hivenance_phase14_scientific_gate_v1",
        "freeze_id":freeze.get("freeze_id"),
        "status":"READY_FOR_ECONOMIC_CONCLUSION" if sufficient else "REFUSE_INSUFFICIENT_PROSPECTIVE_EVIDENCE",
        "books":results,
        "execution_eligible":False,
        "promotion_eligible":False,
        "claim_boundary":{
            "live_execution_authorized":False,
            "historical_replay_counted_as_prospective":False,
        },
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    print("HIVENANCE_PHASE14_SCIENTIFIC_GATE")
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0 if sufficient else 2

if __name__=="__main__":
    raise SystemExit(main())
