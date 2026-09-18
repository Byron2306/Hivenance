#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LARGE_DB_COMPACT_THRESHOLD_BYTES = 512 * 1024 * 1024

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import build_public_client, load_observer_config
from strategies.volatility_breakout.current_truth import (
    _compact_phase2_readiness,
    _materialized_compact_phase2_scorecard,
)
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent) -> None:
        self.store = store

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-2 hypothesis competition")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--settle-only",
        action="store_true",
        help="settle mature persisted forecasts and recompute acceptance without fetching public data",
    )
    parser.add_argument(
        "--compact-scorecard",
        action="store_true",
        help="use bounded recent evidence for fast operational reporting; exact promotion still requires full recompute",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="skip forecast settlement and only recompute/report the current evidence snapshot",
    )
    parser.add_argument("--compact-limit", type=int, default=20000)
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    if args.exchange:
        cfg.exchange = args.exchange
    cfg.phase2_hypotheses_enabled = True
    exchange_id = str(getattr(cfg, "exchange", "kraken") or "kraken").lower()
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    auto_compact_scorecard = False
    try:
        auto_compact_scorecard = db_path.exists() and db_path.stat().st_size >= LARGE_DB_COMPACT_THRESHOLD_BYTES
    except OSError:
        auto_compact_scorecard = False

    store = DataStoreAgent(str(db_path))
    bridge = StoreBridge(store)
    swarm = None
    if not args.settle_only:
        client = build_public_client(exchange_id)
        observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
        swarm = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)

    def collect() -> None:
        compact_mode = bool(args.compact_scorecard or args.settle_only or auto_compact_scorecard)
        scorecard_context = (
            _materialized_compact_phase2_scorecard(store, cfg, limit=int(args.compact_limit))
            if compact_mode
            else store.get_hypothesis_scorecard()
        )
        payload = None if args.settle_only else swarm.run_once(scorecard_context=scorecard_context)
        settlement = (
            {"examined": 0, "settled": 0, "pending": 0, "skipped": "report_only"}
            if args.report_only
            else store.settle_mature_hypothesis_forecasts(
                tolerance_sec=float(getattr(cfg, "phase2_settlement_tolerance_sec", 600) or 600),
                limit=max(1, int(getattr(cfg, "phase2_settlement_batch_limit", 500) or 500)),
                min_target_ts=(
                    time.time() - float(getattr(cfg, "phase2_settlement_max_backlog_age_sec", 6 * 3600) or 6 * 3600)
                ),
                abandon_after_sec=float(getattr(cfg, "phase2_settlement_abandon_after_sec", 3600) or 3600),
            )
        )
        evidence_changed = payload is not None or int(settlement.get("settled") or 0) > 0
        scorecard = (
            (
                _materialized_compact_phase2_scorecard(store, cfg, limit=int(args.compact_limit), force=True)
                if compact_mode
                else store.get_hypothesis_scorecard()
            )
            if evidence_changed
            else scorecard_context
        )
        readiness = (
            _compact_phase2_readiness(store, scorecard, limit=int(args.compact_limit))
            if compact_mode
            else store.get_phase2_readiness(
                min_forecasts=int(getattr(cfg, "phase2_readiness_min_forecasts", 300) or 300),
                min_settled_non_abstain=int(getattr(cfg, "phase2_readiness_min_settled_non_abstain", 100) or 100),
                min_distinct_days=int(getattr(cfg, "phase2_readiness_min_distinct_days", 14) or 14),
                distinct_bucket_hours=int(getattr(cfg, "phase2_readiness_distinct_snapshot_bucket_hours", 24) or 24),
                scorecard=scorecard,
            )
        )
        commons = store.get_commons_phase_summary(2, limit=50)
        dio_gate = store.build_dio_gate_snapshot_from_evidence(
            2, readiness=readiness, scorecard=scorecard, commons=commons,
        )
        if payload is not None:
            payload["readiness"] = {key: value for key, value in readiness.items() if key != "scorecard"}
            payload["dio_gate"] = dio_gate
            store.handle_event({
                "buzz": {"type": "buzz.hypothesis.snapshot", "source": "PHASE2_RUNNER", "ts": int(time.time() * 1000)},
                "payload": payload,
            })
        if args.json:
            print(json.dumps({
                "mode": "settle_only" if args.settle_only else "observe_and_forecast",
                "compact_scorecard": compact_mode,
                "cycle": payload,
                "settlement": settlement,
                "scorecard": scorecard,
                "readiness": readiness,
                "dio_gate": dio_gate,
            }, indent=2, sort_keys=True, default=str))
        elif args.settle_only:
            print(
                f"SETTLEMENT_ONLY settled_now={settlement.get('settled', 0)} "
                f"forecasts={readiness.get('forecasts', 0)} "
                f"settled_non_abstain={readiness.get('settled_non_abstain_forecasts', 0)} "
                f"gate={dio_gate.get('decision')} orders=0"
            )
        else:
            run = payload.get("run") or {}
            calibration = payload.get("walk_forward_calibration") or {}
            research_active = sum(
                1
                for row in payload.get("forecasts") or []
                if not row.get("abstain")
                and not str(row.get("model_id") or "").startswith("baseline_")
            )
            print(
                f"{payload.get('status')} run={run.get('run_id')} "
                f"symbols={run.get('symbols_evaluated', 0)} "
                f"forecasts={run.get('forecasts_total', 0)} "
                f"active={run.get('non_abstain_forecasts', 0)} "
                f"research_active={research_active} "
                f"calibration={calibration.get('allowed', 0)}A/"
                f"{calibration.get('refused', 0)}R/"
                f"{calibration.get('insufficient_evidence', 0)}E "
                f"settled_now={settlement.get('settled', 0)} "
                f"gate={dio_gate.get('decision')} "
                f"compact={1 if compact_mode else 0} orders=0"
            )

    if args.once:
        collect()
        return 0

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    interval = max(30, int(getattr(cfg, "phase1_observation_interval_sec", 120) or 120))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"Phase-2 cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
