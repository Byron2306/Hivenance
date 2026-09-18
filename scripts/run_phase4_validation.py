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

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import build_public_client, load_observer_config
from strategies.volatility_breakout.execution_lab import ExecutionLabAgent
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent
from strategies.volatility_breakout.validation_lab import ValidationLabAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent, cfg: Any | None = None) -> None:
        self.store = store
        self.cfg = cfg

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-4 adversarial validator")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--bootstrap-samples", type=int)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate existing Phase-3 evidence without fetching public data or creating new simulations",
    )
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    if args.exchange:
        cfg.exchange = args.exchange
    cfg.phase4_validation_enabled = True
    if args.max_rows:
        cfg.phase4_max_rows = max(100, int(args.max_rows))
    if args.bootstrap_samples:
        cfg.phase4_bootstrap_samples = max(100, int(args.bootstrap_samples))
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    bridge = StoreBridge(None, cfg)
    store = DataStoreAgent(str(db_path), coordinator=bridge)
    bridge.store = store
    execution_lab = None
    if not args.validate_only:
        exchange_id = str(getattr(cfg, "exchange", "kraken") or "kraken").lower()
        client = build_public_client(exchange_id)
        observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
        hypothesis = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)
        execution_lab = ExecutionLabAgent(cfg, hypothesis, store, coordinator=bridge)
    validator = ValidationLabAgent(cfg, execution_lab, store, coordinator=bridge)

    def collect() -> None:
        payload = validator.run_once(drive_phase3=not args.validate_only)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            readiness = payload.get("readiness") or {}
            pbo = payload.get("pbo") or {}
            champion = payload.get("champion") or {}
            print(
                f"{payload.get('status')} run={payload.get('run_id')} "
                f"rows={payload.get('rows_examined', 0)} candidates={payload.get('candidate_count', 0)} "
                f"pbo={pbo.get('pbo_estimate', 1.0):.3f} "
                f"champion={champion.get('candidate_key', 'none')} "
                f"phase5_review={bool(readiness.get('ready_for_phase5_review'))} real_orders=0"
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
    interval = max(60, int(getattr(cfg, "phase4_interval_sec", 900) or 900))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"Phase-4 cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
