#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from agents.sovereign_pool_worker import SovereignPoolWorker
from scripts.run_phase1_observer import load_observer_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed BEAST/Arda/Sophia/Seraph Hivenance pool worker")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    database = args.database or Path(str(getattr(cfg, "db_path", "data/swarm_data.db")))
    if not database.is_absolute():
        database = ROOT / database
    worker = SovereignPoolWorker(cfg, DataStoreAgent(str(database)), database=database)

    def cycle() -> dict:
        result = worker.process_once(limit=args.limit)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(
                f"{result['status']} claimable={result['claimable']} "
                f"inference={result['inference_receipts']} verifier={result['verifier_receipts']} "
                f"expired={result['expired']} errors={len(result['errors'])}",
                flush=True,
            )
        return result

    if args.once:
        cycle()
        return 0

    stopping = False

    def stop_handler(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    while not stopping:
        started = time.monotonic()
        try:
            cycle()
        except Exception as exc:
            print(f"pool worker cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        delay = max(1.0, float(args.poll_sec) - (time.monotonic() - started))
        deadline = time.monotonic() + delay
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
