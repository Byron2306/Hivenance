#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from dataclasses import asdict
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
from strategies.volatility_breakout.shadow_flight import build_freeze_from_phase4
from strategies.volatility_breakout.shadow_lab import ShadowFlightAgent
from strategies.volatility_breakout.validation_lab import ValidationLabAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent) -> None:
        self.store = store

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def build_stack(cfg: Any, store: DataStoreAgent, *, public_client: Any | None) -> ShadowFlightAgent:
    bridge = StoreBridge(store)
    validation = None
    if public_client is not None:
        observer = ObservationSwarmAgent(cfg, public_client, coordinator=bridge)
        hypothesis = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)
        execution = ExecutionLabAgent(cfg, hypothesis, store, coordinator=bridge)
        validation = ValidationLabAgent(cfg, execution, store, coordinator=bridge)
    return ShadowFlightAgent(cfg, validation, store, coordinator=bridge)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-5 public shadow flight")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--shadow-only",
        action="store_true",
        help="use persisted public observations/forecasts without driving Phases 1-4",
    )
    parser.add_argument("--approve-current-champion", action="store_true")
    parser.add_argument("--approved-by")
    parser.add_argument("--revoke-approval", action="store_true")
    parser.add_argument("--reason", default="human_revocation")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    cfg.phase5_shadow_enabled = True
    if args.exchange:
        cfg.exchange = args.exchange
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = DataStoreAgent(str(db_path))

    if args.revoke_approval:
        ok = store.revoke_phase5_freeze(args.reason)
        print(json.dumps({"revoked": ok, "reason": args.reason}, indent=2))
        return 0 if ok else 1

    if args.approve_current_champion:
        if not args.approved_by:
            parser.error("--approved-by is required with --approve-current-champion")
        report = store.get_phase4_latest_report()
        freeze = build_freeze_from_phase4(
            report,
            approved_by=args.approved_by,
            approved_ts=time.time(),
            cfg=cfg,
        )
        ok = store.persist_phase5_freeze(asdict(freeze))
        print(json.dumps({
            "approved": ok,
            "freeze": asdict(freeze),
            "warning": "This authorizes shadow generation only. It does not authorize order transmission.",
        }, indent=2, sort_keys=True))
        return 0 if ok else 1

    client = None if args.shadow_only else build_public_client(str(getattr(cfg, "exchange", "kraken") or "kraken"))
    lab = build_stack(cfg, store, public_client=client)

    def collect() -> None:
        payload = lab.run_once(drive_upstream=not args.shadow_only)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            readiness = payload.get("readiness") or {}
            settlement = payload.get("settlement") or {}
            print(
                f"{payload.get('status')} run={payload.get('run_id')} "
                f"intents={payload.get('intents_created', 0)} settled={settlement.get('settled', 0)} "
                f"phase6_review={bool(readiness.get('ready_for_phase6_review'))} "
                "transmissions=0 real_orders=0"
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
    interval = max(30, int(getattr(cfg, "phase5_interval_sec", 120) or 120))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"Phase-5 cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        deadline = time.monotonic() + max(1.0, interval - (time.monotonic() - started))
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
