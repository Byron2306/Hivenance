#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from strategies.relative_value_lab.ablation_lab import AblationSnapshot, RelativeValueAblationLab
from strategies.relative_value_lab.contracts import RELATIVE_VALUE_AUTHORITY
from strategies.relative_value_lab.settlement import SettledRelativeForecast


def parse_args() -> argparse.Namespace:
    p=argparse.ArgumentParser(description="Replay a frozen prospective HiveNance ablation corpus")
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,default=Path("data/pollen_ablation_replay.json"))
    return p.parse_args()


def _settlement(case:dict) -> SettledRelativeForecast:
    snap=case["snapshot"]
    ts=int(snap.get("forecast_timestamp_ms") or 0)
    return SettledRelativeForecast(
        schema="hivenance_settled_relative_forecast_v1",
        forecast_id=str(case["forecast_id"]),
        pair_id=str(case["pair_id"]),
        model_id="prospective_replay",
        forecast_timestamp_ms=ts,
        target_timestamp_ms=ts+1,
        settled_timestamp_ms=ts+1,
        horizon_seconds=1,
        direction="LONG_A_SHORT_B",
        entry_spread=0.0,
        settled_spread=0.0,
        predicted_signed_move_bps=None,
        realized_signed_move_bps=float(case["net_bps"]),
        realized_directional_gross_bps=float(case["net_bps"]),
        expected_cost_bps=0.0,
        realized_directional_net_bps=float(case["net_bps"]),
        forecast_error_bps=None,
        abstain=False,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def main()->int:
    args=parse_args()
    payload=json.loads(args.input.read_text(encoding="utf-8"))
    cases=payload.get("replay_cases") or []
    if not cases:
        raise SystemExit(
            "Input has no replay_cases. Generate a fresh ablation file with the "
            "current gauntlet first."
        )

    lab=RelativeValueAblationLab()
    for case in cases:
        lab.freeze(AblationSnapshot(**case["snapshot"]))
        lab.settle(_settlement(case))

    report=lab.report()
    out={
        **report.to_dict(),
        "deltas_vs_full_hive":[row.__dict__ for row in lab.deltas()],
        "replay_source":str(args.input),
        "replay_case_count":len(cases),
        "authority":RELATIVE_VALUE_AUTHORITY,
        "execution_eligible":False,
        "promotion_eligible":False,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"replayed={len(cases)}")
    print(f"output={args.output}")
    print("AUTHORITY: research_evidence_only_no_execution_or_promotion_authority")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
