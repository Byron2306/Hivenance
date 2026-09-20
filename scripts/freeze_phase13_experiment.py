#!/usr/bin/env python3
from __future__ import annotations

import argparse,json
from pathlib import Path
from types import SimpleNamespace
from strategies.relative_value_lab.organ_topology import ORGANS
from strategies.relative_value_lab.phase13_experiment import build_phase13_freeze
from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("data/phase13_experiment_freeze.json"))
    ap.add_argument("--minimum-samples",type=int,default=30)
    ap.add_argument("--minimum-worlds",type=int,default=20)
    ap.add_argument("--recurrence-bound",type=int,default=3)
    ap.add_argument("--exchange",default="kraken")
    ap.add_argument("--reference-notional-usd",type=float,default=5.0)
    ap.add_argument("--latency-buffer-bps",type=float,default=2.0)
    ap.add_argument("--safety-buffer-bps",type=float,default=3.0)
    ap.add_argument("--max-total-cost-bps",type=float,default=150.0)
    args=ap.parse_args()

    # Intentionally self-contained: freezing the Phase-13 research contract
    # must not import the full coordinator/security stack. This keeps the
    # command deterministic and Termux-safe even when optional cryptography
    # bindings are unavailable.
    cfg=SimpleNamespace(
        exchange=str(args.exchange),
        live_mode=False,
        dry_run=True,
        phase2_reference_notional_usd=float(args.reference_notional_usd),
        phase2_latency_buffer_bps=float(args.latency_buffer_bps),
        phase2_safety_buffer_bps=float(args.safety_buffer_bps),
        phase2_max_total_cost_bps=float(args.max_total_cost_bps),
        phase2_worker_signal_federation_enabled=True,
        phase2_worker_coalition_enabled=True,
        medium_trend_phase2_model_enabled=True,
        derivatives_trend_phase2_model_enabled=True,
    )
    comp=HypothesisCompetition(cfg)

    freeze=build_phase13_freeze(
        organ_roster=[x.organ_id for x in ORGANS],
        model_roster=comp.all_model_ids,
        queen_epoch_rules={
            "source":"canonical_conducting_queen",
            "recurrence_bound":int(args.recurrence_bound),
            "same_world_root_required":True,
        },
        recurrence_bound=int(args.recurrence_bound),
        comparison_rules={
            "timestamp_safe":True,
            "future_reference_forbidden":True,
            "selected_rejected_preserved":True,
            "controls_first_class":True,
        },
        cost_model={
            "exchange":str(getattr(cfg,"exchange","kraken")),
            "phase2_reference_notional_usd":getattr(cfg,"phase2_reference_notional_usd",None),
            "phase2_latency_buffer_bps":getattr(cfg,"phase2_latency_buffer_bps",None),
            "phase2_safety_buffer_bps":getattr(cfg,"phase2_safety_buffer_bps",None),
            "phase2_max_total_cost_bps":getattr(cfg,"phase2_max_total_cost_bps",None),
        },
        minimum_samples=int(args.minimum_samples),
        minimum_distinct_market_worlds=int(args.minimum_worlds),
    )
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(freeze.to_dict(),indent=2,sort_keys=True),encoding="utf-8")
    print("HIVENANCE_PHASE13_EXPERIMENT_FROZEN")
    print(json.dumps(freeze.to_dict(),indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
