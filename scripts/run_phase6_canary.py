#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.canary_lab import (
    PHASE6_ACKNOWLEDGEMENT,
    TinyLiveCanary,
    build_canary_approval,
)
from strategies.volatility_breakout.canary_store import CanaryStore
from strategies.volatility_breakout.kraken_canary import KrakenRestClient


def build_private_client(cfg: Any) -> KrakenRestClient | None:
    key = os.environ.get("HIVENANCE_KRAKEN_API_KEY", "").strip()
    secret = os.environ.get("HIVENANCE_KRAKEN_API_SECRET", "").strip()
    if not key or not secret:
        return None
    return KrakenRestClient(
        key,
        secret,
        base_url=str(getattr(cfg, "phase6_private_api_base_url", "https://api.kraken.com") or "https://api.kraken.com"),
        timeout_sec=float(getattr(cfg, "phase6_private_api_timeout_sec", 10.0) or 10.0),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-6 isolated tiny-live Kraken canary")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path, default=ROOT / "config/volatility_breakout_phase6.yaml")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live", action="store_true", help="request live submission; still requires config, env interlock and active approval")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--reconcile-only", action="store_true")
    parser.add_argument("--approve-canary", action="store_true")
    parser.add_argument("--approved-by")
    parser.add_argument("--ack-live-risk")
    parser.add_argument("--revoke-approval", action="store_true")
    parser.add_argument("--reason", default="human_revocation")
    parser.add_argument("--halt", action="store_true")
    parser.add_argument("--emergency-cancel-all", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/swarm_data.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    data_store = DataStoreAgent(str(db_path))
    phase6_store = CanaryStore(data_store)

    if args.approve_canary:
        if not args.approved_by:
            parser.error("--approved-by is required")
        if args.ack_live_risk != PHASE6_ACKNOWLEDGEMENT:
            parser.error(f"--ack-live-risk must exactly equal: {PHASE6_ACKNOWLEDGEMENT!r}")
        approval = build_canary_approval(
            data_store,
            cfg,
            approved_by=args.approved_by,
            acknowledgement=args.ack_live_risk,
        )
        phase6_store.persist_approval(approval.to_dict())
        print(json.dumps({
            "approved": True,
            "approval": approval.to_dict(),
            "warning": "Approval is short-lived, capped at one tiny entry, and does not bypass the separate environment interlock.",
        }, indent=2, sort_keys=True))
        return 0

    if args.revoke_approval:
        changed = phase6_store.revoke_approval(args.reason)
        print(json.dumps({"revoked": changed, "reason": args.reason}, indent=2))
        return 0 if changed else 1

    if args.halt:
        phase6_store.set_state("HALTED", f"manual_halt:{args.reason}")
        print(json.dumps({"halted": True, "reason": args.reason}, indent=2))
        return 0

    client = build_private_client(cfg)
    canary = TinyLiveCanary(cfg, data_store, client)

    if args.live:
        if args.once:
            parser.error("--live cannot be combined with --once; the live canary requires a continuous supervised operator process")
        if not bool(getattr(cfg, "phase6_live_submission_enabled", False)):
            parser.error("the selected local profile must explicitly set phase6_live_submission_enabled: true")
        if os.environ.get("HIVENANCE_PHASE6_LIVE_SUBMISSION", "").strip().upper() != "YES":
            parser.error("HIVENANCE_PHASE6_LIVE_SUBMISSION=YES is required for live canary authority")
        if client is None:
            parser.error("HIVENANCE_KRAKEN_API_KEY and HIVENANCE_KRAKEN_API_SECRET are required")

    if args.status:
        print(json.dumps(canary.snapshot(), indent=2, sort_keys=True, default=str))
        return 0

    if args.emergency_cancel_all:
        if client is None:
            parser.error("Kraken environment credentials are required")
        result = client.cancel_all()
        phase6_store.set_state("HALTED", "emergency_cancel_all_invoked", payload=result)
        print(json.dumps({"canceled": True, "result": result, "state": "HALTED"}, indent=2, default=str))
        return 0

    if args.reconcile_only:
        if client is None:
            parser.error("Kraken environment credentials are required")
        try:
            result = canary.reconcile()
        except Exception as exc:
            print(json.dumps({"status": "HALTED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
            return 2
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0

    def cycle() -> None:
        result = canary.run_once(live_requested=args.live)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True, default=str))
        else:
            print(
                f"{result.get('status')} state={result.get('state')} "
                f"validated={result.get('validate_only_calls', 0)} "
                f"attempts={result.get('live_submission_attempts', 0)} "
                f"submitted={result.get('live_orders_submitted', 0)}"
            )

    if args.once:
        cycle()
        return 0

    stopping = False
    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    interval = max(5, int(getattr(cfg, "phase6_deadman_refresh_sec", 20) or 20))
    while not stopping:
        started = time.monotonic()
        try:
            cycle()
        except Exception as exc:
            phase6_store.set_state("HALTED", f"operator_process_exception:{type(exc).__name__}", payload={"error": str(exc)})
            print(f"Phase-6 canary cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))

    if args.live and client is not None:
        cleanup: dict[str, Any] = {"pending_orders_canceled": False}
        try:
            cleanup["cancel_all_result"] = client.cancel_all()
            cleanup["pending_orders_canceled"] = True
        except Exception as exc:
            cleanup["cancel_all_error"] = f"{type(exc).__name__}: {exc}"
        open_position = phase6_store.get_open_position()
        if open_position:
            phase6_store.set_state(
                "EXIT_ONLY",
                "operator_process_stopped_with_open_spot_inventory",
                payload={"position": open_position, "cleanup": cleanup},
            )
            print(
                "CRITICAL: Phase-6 operator stopped with open spot inventory. "
                "Pending orders were cancellation-attempted, but dead-man cancellation does not liquidate holdings. "
                "Restart the operator and reconcile immediately.",
                file=sys.stderr,
            )
            return 3
        phase6_store.set_state("HALTED", "operator_process_stopped", payload=cleanup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
