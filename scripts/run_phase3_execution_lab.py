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


class StoreBridge:
    def __init__(self, store: DataStoreAgent, cfg: Any | None = None) -> None:
        self.store = store
        self.cfg = cfg

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-3 execution-aware simulator")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-forecasts", type=int)
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="simulate already settled Phase-2 forecasts without fetching new public data",
    )
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    if args.exchange:
        cfg.exchange = args.exchange
    cfg.phase2_hypotheses_enabled = True
    cfg.phase3_execution_lab_enabled = True
    if args.max_forecasts:
        cfg.phase3_max_forecasts_per_cycle = max(1, int(args.max_forecasts))
    exchange_id = str(getattr(cfg, "exchange", "kraken") or "kraken").lower()
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    bridge = StoreBridge(None, cfg)
    store = DataStoreAgent(str(db_path), coordinator=bridge)
    bridge.store = store
    hypothesis = None
    if not args.replay_only:
        client = build_public_client(exchange_id)
        observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
        hypothesis = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)
    lab = ExecutionLabAgent(cfg, hypothesis, store, coordinator=bridge)

    def collect() -> None:
        payload = lab.run_once(drive_phase2=not args.replay_only)
        scorecard = store.get_execution_scorecard()
        readiness = store.get_phase3_readiness(
            min_completed=int(getattr(cfg, "phase3_readiness_min_completed", 100) or 100),
            max_mean_2x_loss_bps=float(
                getattr(cfg, "phase3_readiness_max_mean_2x_loss_bps", 50.0) or 50.0
            ),
        )
        if args.json:
            print(json.dumps(
                {"cycle": payload, "scorecard": scorecard, "readiness": readiness},
                indent=2, sort_keys=True, default=str,
            ))
        else:
            run = payload.get("run") or {}
            print(
                f"{payload.get('status')} run={run.get('run_id')} "
                f"forecasts={run.get('forecasts_examined', 0)} "
                f"simulations={run.get('simulations_created', 0)} "
                f"completed={run.get('completed', 0)} rejected={run.get('rejected', 0)} "
                f"expired={run.get('expired', 0)} real_orders=0"
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
    interval = max(30, int(getattr(cfg, "phase3_interval_sec", 120) or 120))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"Phase-3 cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
