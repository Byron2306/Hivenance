#!/usr/bin/env python3
"""Compute the Hivenance acceptance-governor next research action.

The acceptance governor inspects CURRENT_TRUTH.json, the active Phase-5 frozen
champion, and the persisted Phase-6 deterministic soak report to decide the
single cheapest, safe next research action across the Phase 1-6 evidence-gate
ladder. It never submits orders and never mutates state on its own; it only
recommends a next step and, with --execute, will run that step's command if
(and only if) the governor marked it safe to auto-execute.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.acceptance_governor import (
    decide_next_action,
    load_phase6_soak_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decide the next safe Hivenance research-acceptance action across Phase 1-6"
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange", default="kraken")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--truth", type=Path, default=ROOT / "CURRENT_TRUTH.json")
    parser.add_argument(
        "--phase6-soak-report",
        type=Path,
        default=ROOT / "PHASE6_SYNTHETIC_CANARY_REPORT.json",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run the recommended action's command if the governor marked it safe to auto-execute",
    )
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    data_store = DataStoreAgent(str(db_path))

    truth = load_phase6_soak_report(args.truth)
    active_freeze = data_store.get_phase5_active_freeze() or {}
    soak_report = load_phase6_soak_report(args.phase6_soak_report)

    decision = decide_next_action(
        truth=truth,
        cfg=cfg,
        root=ROOT,
        settings=args.settings,
        exchange=args.exchange,
        active_freeze=active_freeze,
        phase6_soak_report=soak_report,
        profile=args.profile,
        database=args.database,
    )

    print(json.dumps(decision.to_dict(), indent=2, sort_keys=True, default=str))

    if not args.execute:
        return 0

    action = decision.next_action
    if not action.command:
        print(f"no command to execute for action={action.action}", file=sys.stderr)
        return 0
    if not action.safe_to_auto_execute:
        print(
            f"refusing to auto-execute {action.action}: requires_human={action.requires_human}",
            file=sys.stderr,
        )
        return 1
    completed = subprocess.run(action.command, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
