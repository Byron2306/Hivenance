#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from strategies.relative_value_lab.phase13_settlement_runtime import (
    settle_mature_phase13_books,
)


def main()->int:
    ap=argparse.ArgumentParser(description="Settle mature Phase-13 forecast-book rows from public observations")
    ap.add_argument("--freeze",type=Path,default=Path("data/phase13_experiment_freeze.json"))
    ap.add_argument("--ledger",type=Path,default=Path("data/hivenance_phase13_books.db"))
    ap.add_argument("--market-db",type=Path,default=Path("data/swarm_data.db"))
    ap.add_argument("--out",type=Path,default=Path("data/phase13_settlement_book.json"))
    ap.add_argument("--tolerance-sec",type=float,default=1800.0)
    ap.add_argument("--limit",type=int,default=10000)
    ap.add_argument("--as-of-ts",type=float,default=None)
    args=ap.parse_args()

    freeze=json.loads(args.freeze.read_text(encoding="utf-8"))
    freeze_id=str(freeze.get("freeze_id") or "")
    if not freeze_id:
        raise ValueError("phase13_freeze_id_missing")

    result=settle_mature_phase13_books(
        freeze_id=freeze_id,
        ledger_path=args.ledger,
        market_db_path=args.market_db,
        as_of_ts=args.as_of_ts,
        tolerance_sec=float(args.tolerance_sec),
        limit=int(args.limit),
    )
    book=result.get("settlement_book") or {}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(book,indent=2,sort_keys=True),encoding="utf-8")

    print("HIVENANCE_PHASE13_SETTLEMENT")
    for key in (
        "freeze_id","pending_examined","settled","abstained","awaiting",
        "no_mature_public_tape","total_exported"
    ):
        print(f"{key}=",result.get(key))
    print("errors=",len(result.get("errors") or []))
    print("execution_eligible=False")
    print("promotion_eligible=False")
    print("out=",args.out)
    return 0 if not result.get("errors") else 2


if __name__=="__main__":
    raise SystemExit(main())
