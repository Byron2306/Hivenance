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

    client = build_public_client(exchange_id)
    store = DataStoreAgent(str(db_path))
    bridge = StoreBridge(store)
    observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
    swarm = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)

    def collect() -> None:
        payload = swarm.run_once()
        settlement = store.settle_mature_hypothesis_forecasts(
            tolerance_sec=float(getattr(cfg, "phase2_settlement_tolerance_sec", 600) or 600)
        )
        scorecard = store.get_hypothesis_scorecard()
        if args.json:
            print(json.dumps({"cycle": payload, "settlement": settlement, "scorecard": scorecard}, indent=2, sort_keys=True, default=str))
        else:
            run = payload.get("run") or {}
            print(
                f"{payload.get('status')} run={run.get('run_id')} "
                f"symbols={run.get('symbols_evaluated', 0)} "
                f"forecasts={run.get('forecasts_total', 0)} "
                f"active={run.get('non_abstain_forecasts', 0)} "
                f"settled_now={settlement.get('settled', 0)} orders=0"
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
