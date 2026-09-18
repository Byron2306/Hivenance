#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_phase1_observer import load_observer_config


def build_steps(args: argparse.Namespace) -> list[tuple[str, list[str]]]:
    common = ["--settings", str(args.settings), "--exchange", args.exchange]
    if args.profile:
        common.extend(["--profile", str(args.profile)])
    if args.database:
        common.extend(["--database", str(args.database)])
    phase5 = [
        sys.executable, str(ROOT / "scripts/run_phase5_shadow_flight.py"), *common,
        "--once",
    ]
    if args.offline:
        phase5.append("--shadow-only")
    if args.phase5_only:
        return [("Phase 5 shadow economics", phase5)]
    phase4 = [
        sys.executable, str(ROOT / "scripts/run_phase4_validation.py"), *common,
        "--once", "--validate-only",
    ]
    if args.phase4_only:
        return [("Phase 4 adversarial validation", phase4)]

    phase3 = [
        sys.executable, str(ROOT / "scripts/run_phase3_execution_lab.py"), *common,
        "--once", "--replay-only", "--compact-scorecard",
    ]
    if args.phase3_only:
        return [("Phase 3 deterministic execution replay and acceptance", phase3)]

    phase2 = [
        sys.executable, str(ROOT / "scripts/run_phase2_hypotheses.py"), *common, "--once", "--compact-scorecard",
    ]
    if args.offline:
        phase2.append("--settle-only")
    steps = [
        ("Phase 2 hypothesis settlement and acceptance", phase2),
        ("Phase 3 deterministic execution replay and acceptance", phase3),
    ]
    if not args.skip_phase4:
        steps.append(("Phase 4 adversarial validation", phase4))
    return steps


def run_cycle(args: argparse.Namespace, timeout_sec: float) -> bool:
    cycle_started = time.monotonic()
    mode = (
        "phase5-only"
        if args.phase5_only
        else (
            "phase4-only"
            if args.phase4_only
            else ("phase3-only" if args.phase3_only else "sequential research acceptance")
        )
    )
    print(
        f"\n[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] "
        f"starting {mode} cycle",
        flush=True,
    )
    for label, command in build_steps(args):
        started = time.monotonic()
        print(f"START {label}", flush=True)
        try:
            completed = subprocess.run(command, cwd=ROOT, timeout=timeout_sec, check=False)
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT {label} after {timeout_sec:.0f}s; downstream phases not run", flush=True)
            return False
        elapsed = time.monotonic() - started
        if completed.returncode != 0:
            print(
                f"FAILED {label} exit={completed.returncode} elapsed={elapsed:.1f}s; "
                "downstream phases not run",
                flush=True,
            )
            return False
        print(f"COMPLETE {label} elapsed={elapsed:.1f}s", flush=True)

    truth_command = [
        sys.executable,
        str(ROOT / "scripts/render_current_truth.py"),
        "--settings",
        str(args.settings),
        "--output",
        str(args.truth_output),
    ]
    if args.profile:
        truth_command.extend(["--profile", str(args.profile)])
    if args.database:
        truth_command.extend(["--database", str(args.database)])
    truth = subprocess.run(truth_command, cwd=ROOT, timeout=120, check=False)
    if truth.returncode != 0:
        print(f"WARNING current truth render failed exit={truth.returncode}", flush=True)
    print(f"CYCLE COMPLETE elapsed={time.monotonic() - cycle_started:.1f}s real_orders=0", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run research acceptance gates; defaults can narrow execution gate-by-gate"
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange", default="kraken")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--interval-sec", type=float)
    parser.add_argument("--phase-timeout-sec", type=float)
    parser.add_argument("--skip-phase4", action="store_true")
    parser.add_argument(
        "--phase5-only",
        dest="phase5_only",
        action="store_true",
        help="run only Phase 5 shadow economics; skip Phase 2, Phase 3, and Phase 4",
    )
    parser.add_argument(
        "--phase4-only",
        "--skip-phase2-phase3",
        dest="phase4_only",
        action="store_true",
        help="run only Phase 4 validation; skip Phase 2 and Phase 3 for Phase-4-only optimization",
    )
    parser.add_argument(
        "--phase3-only",
        "--skip-phase2",
        dest="phase3_only",
        action="store_true",
        help="run only Phase 3 replay/acceptance; skip Phase 2 and Phase 4 for gate-by-gate optimization",
    )
    parser.add_argument(
        "--include-phase2",
        action="store_true",
        help="override research_pipeline_phase3_only config and run the full Phase 2 -> Phase 3 path",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="settle and replay persisted evidence without fetching public market data",
    )
    parser.add_argument("--truth-output", type=Path, default=ROOT / "CURRENT_TRUTH.json")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    configured_phase5_only = bool(getattr(cfg, "research_pipeline_phase5_only", False))
    configured_phase4_only = bool(getattr(cfg, "research_pipeline_phase4_only", False))
    configured_phase3_only = bool(getattr(cfg, "research_pipeline_phase3_only", False))
    if configured_phase5_only:
        args.phase5_only = True
        args.phase4_only = False
        args.phase3_only = False
    elif configured_phase4_only:
        args.phase4_only = True
        args.phase3_only = False
    elif configured_phase3_only and not args.include_phase2:
        args.phase3_only = True
    interval_sec = max(
        300.0,
        float(args.interval_sec or getattr(cfg, "research_pipeline_interval_sec", 3600) or 3600),
    )
    timeout_sec = max(
        60.0,
        float(args.phase_timeout_sec or getattr(cfg, "research_pipeline_phase_timeout_sec", 2700) or 2700),
    )

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    while not stopping:
        cycle_started = time.monotonic()
        success = run_cycle(args, timeout_sec)
        if args.once:
            return 0 if success else 1
        remaining = max(1.0, interval_sec - (time.monotonic() - cycle_started))
        print(f"NEXT CYCLE in {remaining:.0f}s", flush=True)
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
