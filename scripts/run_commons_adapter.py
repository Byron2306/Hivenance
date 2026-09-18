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

from agents.commons_adapter import CommonsAdapter
from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Commons adapter inbox processor")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--inbox-dir", type=Path, default=ROOT / "data/commons_inbox")
    parser.add_argument("--archive-dir", type=Path, default=ROOT / "data/commons_archive")
    parser.add_argument("--poll-sec", type=float, default=15.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    adapter = CommonsAdapter(
        DataStoreAgent(str(db_path)),
        inbox_dir=args.inbox_dir,
        archive_dir=args.archive_dir,
    )

    def cycle() -> dict:
        summary = adapter.process_once()
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(
                f"processed={summary.get('processed', 0)} "
                f"accepted={summary.get('accepted', 0)} "
                f"rejected={summary.get('rejected', 0)}"
            )
        return summary

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
            print(f"Commons adapter cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, float(args.poll_sec) - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
