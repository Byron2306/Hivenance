#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.execution_lab import ExecutionLabAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent | None, cfg: Any) -> None:
        self.store = store
        self.cfg = cfg

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        if self.store:
            self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Expand Phase-3 evidence with an outcome-blind stratified replay sample"
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--model-id", default="candidate_freqai_transparent_linear_v1")
    parser.add_argument("--order-policy", default="passive_then_chase")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--max-per-symbol", type=int, default=10)
    parser.add_argument("--max-per-hour-bucket", type=int, default=4)
    parser.add_argument("--scenarios", default="normal,cost_1_5x,cost_2x,liquidity_stress,infrastructure_stress")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    cfg.phase3_execution_lab_enabled = True
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/swarm_data.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    bridge = StoreBridge(None, cfg)
    store = DataStoreAgent(str(db_path), coordinator=bridge)
    bridge.store = store
    lab = ExecutionLabAgent(cfg, None, store, coordinator=bridge)
    if args.order_policy not in lab.policies:
        raise ValueError(f"unsupported order policy: {args.order_policy}")
    requested_scenarios = tuple(item.strip() for item in str(args.scenarios).split(",") if item.strip())
    scenarios = tuple(item for item in requested_scenarios if item in lab.scenarios)
    if not scenarios or len(scenarios) != len(requested_scenarios):
        raise ValueError("one or more requested scenarios are unsupported")

    candidates = store.get_phase3_evidence_expansion_candidates(
        model_id=args.model_id,
        order_policy=args.order_policy,
        limit=max(1, int(args.limit)),
        min_expected_net_bps=float(getattr(cfg, "phase3_min_expected_net_bps", 10.0) or 10.0),
        min_probability_positive_net=float(
            getattr(cfg, "phase3_min_probability_positive_net", 0.58) or 0.58
        ),
        max_per_symbol=max(1, int(args.max_per_symbol)),
        max_per_hour_bucket=max(1, int(args.max_per_hour_bucket)),
    )
    started_ms = int(time.time() * 1000)
    run_id = f"sim-expand-{started_ms}-{uuid.uuid4().hex[:8]}"
    admissions = [lab._phase3_admission_receipt(candidate, started_ms) for candidate in candidates]
    admitted = [candidate for candidate, receipt in zip(candidates, admissions) if receipt.get("admitted")]
    refused = [receipt for receipt in admissions if not receipt.get("admitted")]
    selection_manifest = {
        "schema": "phase3_evidence_expansion_manifest_v1",
        "model_id": args.model_id,
        "order_policy": args.order_policy,
        "scenarios": list(scenarios),
        "selection_order": "forecast_ts_ascending_then_forecast_id",
        "selection_fields": [
            "model_id", "expected_net_bps", "probability_positive_net",
            "forecast_ts", "symbol", "hour_bucket",
        ],
        "outcome_fields_excluded_from_selection": [
            "exit_price", "directional_return_bps", "net_return_bps",
        ],
        "max_per_symbol": max(1, int(args.max_per_symbol)),
        "max_per_hour_bucket": max(1, int(args.max_per_hour_bucket)),
        "candidate_forecast_ids": [candidate.get("forecast_id") for candidate in candidates],
        "admitted_forecast_ids": [candidate.get("forecast_id") for candidate in admitted],
        "authority": "research_only",
        "execution_eligible": False,
    }
    selection_manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(selection_manifest, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()

    simulations = []
    skipped_existing = 0
    for candidate in admitted:
        for scenario in scenarios:
            simulation_id = hashlib.sha256(
                f"{candidate.get('forecast_id')}:{args.order_policy}:{scenario}:{lab.simulator.simulator_version}".encode()
            ).hexdigest()
            if store.simulation_exists(simulation_id):
                skipped_existing += 1
                continue
            row = lab.simulator.simulate(
                candidate,
                run_id=run_id,
                order_policy=args.order_policy,
                scenario=scenario,
            ).to_dict()
            row["evidence_expansion"] = {
                "manifest_hash": selection_manifest["manifest_hash"],
                "authority": "research_only",
                "execution_eligible": False,
            }
            if not store.persist_execution_simulation(row):
                raise RuntimeError(f"failed to persist expansion simulation {simulation_id}")
            simulations.append(row)

    completed_ms = int(time.time() * 1000)
    run = {
        "run_id": run_id,
        "started_at_ms": started_ms,
        "completed_at_ms": completed_ms,
        "forecasts_considered": len(candidates),
        "forecasts_examined": len(admitted),
        "forecasts_admitted": len(admitted),
        "forecasts_refused_pre_simulation": len(refused),
        "simulations_created": len(simulations),
        "simulations_skipped_existing": skipped_existing,
        "completed": sum(row.get("status") == "COMPLETED" for row in simulations),
        "rejected": sum(row.get("status") == "REJECTED" for row in simulations),
        "expired": sum(row.get("status") == "EXPIRED" for row in simulations),
        "execution_wired": False,
        "real_orders_submitted": 0,
    }
    scorecard = store.get_execution_scorecard()
    readiness = store.get_phase3_readiness(
        min_completed=int(getattr(cfg, "phase3_readiness_min_completed", 100) or 100),
        max_mean_2x_loss_bps=float(getattr(cfg, "phase3_readiness_max_mean_2x_loss_bps", 50.0) or 50.0),
        scorecard=scorecard,
    )
    commons = store.get_commons_phase_summary(3, limit=50)
    gate = store.build_dio_gate_snapshot_from_evidence(
        3, readiness=readiness, scorecard=scorecard, commons=commons,
    )
    payload = {
        "phase": 3,
        "mode": "deterministic_evidence_expansion_only",
        "status": "EVIDENCE_EXPANDED" if simulations else "NO_EXPANSION_CANDIDATES",
        "run": run,
        "selection_manifest": selection_manifest,
        "phase3_admission": {"receipts": admissions, "refusals": refused},
        "simulations": simulations,
        "readiness": {key: value for key, value in readiness.items() if key != "scorecard"},
        "dio_gate": gate,
        "execution_wired": False,
        "real_orders_submitted": 0,
    }
    payload["dataset_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    store.persist_simulation_run(payload)
    output = {
        "status": payload["status"],
        "run": run,
        "selection_manifest": selection_manifest,
        "dio_gate": gate,
    }
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"{payload['status']} run={run_id} selected={len(candidates)} admitted={len(admitted)} "
            f"symbols={len({candidate.get('symbol') for candidate in admitted})} "
            f"simulations={len(simulations)} completed={run['completed']} rejected={run['rejected']} "
            f"gate={gate.get('decision')} real_orders=0"
        )
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
