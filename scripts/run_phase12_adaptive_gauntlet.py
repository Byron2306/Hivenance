#!/usr/bin/env python3
"""Phase 12 adaptive whole-organism public-market gauntlet.

This is a research-only runtime harness:
- boots the full SwarmCoordinator research stack;
- uses public market data only;
- forces dry-run / no-order safety;
- loads reversible organ runtime modes from the latest full census;
- runs repeated upstream + shadow settlement cycles;
- supports fixed-duration or continuous operation;
- writes a durable receipt for tmux/unattended runs.

ACTIVE means active research influence only. This harness never authorizes orders.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

# Termux/Python cryptography Rust-binding safeguard used by the G1 gauntlet.
if os.environ.get("PREFIX") and not os.environ.get("HIVENANCE_PHASE12_PRELOAD_DONE"):
    libpython = Path(os.environ["PREFIX"]) / "lib" / f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
    if libpython.exists():
        env = dict(os.environ)
        existing = env.get("LD_PRELOAD", "").strip()
        env["LD_PRELOAD"] = str(libpython) if not existing else str(libpython) + ":" + existing
        env["HIVENANCE_PHASE12_PRELOAD_DONE"] = "1"
        os.execve(sys.executable, [sys.executable, *sys.argv], env)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.coordinator import SwarmCoordinator
from agents.kraken_public_client import KrakenPublicClient
from main import apply_phase0_safety_policy, load_config

STOP = False


def _stop(_sig: int, _frame: Any) -> None:
    global STOP
    STOP = True


def _find_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = _find_key(child, key)
            if found is not None:
                return found
    return None


def _load_control_plane(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("organ_runtime_control")
    if not isinstance(rows, dict):
        return {}
    return {
        str(organ_id): dict(state)
        for organ_id, state in rows.items()
        if isinstance(state, dict)
    }


def _stop_agents(coordinator: SwarmCoordinator) -> None:
    for agent in list(getattr(coordinator, "agents", {}).values()):
        stop = getattr(agent, "stop", None)
        if not callable(stop):
            continue
        try:
            stop()
        except TypeError:
            try:
                stop(timeout=1)
            except Exception:
                pass
        except Exception:
            pass
    coordinator.running = False


def _mode_summary(control_plane: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for organ_id, state in sorted(control_plane.items()):
        mode = str(state.get("mode") or "UNKNOWN")
        out.setdefault(mode, []).append(organ_id)
    return out


def _cycle_summary(payload: dict[str, Any]) -> dict[str, Any]:
    upstream = payload.get("upstream_cycle") if isinstance(payload.get("upstream_cycle"), dict) else {}
    g0 = _find_key(upstream, "g0_prospective") or {}
    settlement = payload.get("settlement") if isinstance(payload.get("settlement"), dict) else {}
    organs = g0.get("by_organ") if isinstance(g0.get("by_organ"), dict) else {}
    return {
        "status": payload.get("status"),
        "features_examined": int(g0.get("features_examined") or 0),
        "eligible": int(g0.get("eligible") or 0),
        "diverged": int(g0.get("diverged") or 0),
        "frozen": int(g0.get("frozen") or 0),
        "raw_non_abstain": sum(int((row or {}).get("raw_non_abstain") or 0) for row in organs.values()),
        "twins_settled": int(settlement.get("g0_twins_settled") or 0),
        "settled": int(settlement.get("settled") or 0),
        "organ_divergence": {
            str(organ_id): int((row or {}).get("diverged") or 0)
            for organ_id, row in organs.items()
            if int((row or {}).get("diverged") or 0) > 0
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phase 12 adaptive whole-organism gauntlet")
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--hours", type=float, help="wall-clock duration; e.g. 6, 12, 24")
    duration.add_argument("--continuous", action="store_true", help="run until SIGINT/SIGTERM")
    parser.add_argument("--pause-sec", type=float, default=15.0)
    parser.add_argument("--quiet-kraken", action="store_true")
    parser.add_argument(
        "--census",
        type=Path,
        default=ROOT / "data" / "full_organism_census.json",
        help="latest census containing organ_runtime_control",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=ROOT / "data" / "phase12_adaptive_gauntlet_latest.json",
    )
    args = parser.parse_args()

    hours = 6.0 if args.hours is None and not args.continuous else args.hours
    if hours is not None and hours <= 0:
        parser.error("--hours must be > 0")
    pause = max(0.0, float(args.pause_sec))

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    control_plane = _load_control_plane(args.census)
    print("HIVENANCE_PHASE12_ADAPTIVE_GAUNTLET")
    print("research_only=True")
    print("execution_eligible=False")
    print("promotion_eligible=False")
    print("real_orders_submitted=0")
    print("duration=", "CONTINUOUS" if args.continuous else f"{hours}h")
    print("census=", str(args.census))
    print("runtime_modes=", json.dumps(_mode_summary(control_plane), sort_keys=True), flush=True)

    cfg = apply_phase0_safety_policy(load_config())

    # Hard safety boundary.
    cfg.live_mode = False
    cfg.dry_run = True
    cfg.phase5_shadow_enabled = True
    cfg.phase6_canary_enabled = False
    cfg.phase6_live_submission_enabled = False
    cfg.phase7_growth_enabled = False
    cfg.phase7_stage_activation_enabled = False
    cfg.kraken_api_key = ""
    cfg.kraken_api_secret = ""
    cfg.binance_api_key = ""
    cfg.binance_api_secret = ""

    # Expose the reversible control plane to the full coordinator. Existing
    # organs that do not yet consume it remain observable; this field is the
    # canonical runtime handoff for progressive wiring.
    cfg.phase12_adaptive_organism_enabled = True
    cfg.phase12_organ_runtime_modes = {
        organ_id: str(state.get("mode") or "SHADOW")
        for organ_id, state in control_plane.items()
    }
    cfg.phase12_organ_runtime_control = control_plane

    client = KrakenPublicClient(progress=not args.quiet_kraken) if str(cfg.exchange).lower() == "kraken" else None
    coordinator = SwarmCoordinator(cfg)
    coordinator.phase12_organ_runtime_control = control_plane
    coordinator.initialize(client)

    shadow = coordinator.agents.get("shadow_flight")
    if shadow is None:
        raise RuntimeError("shadow_flight_agent_unavailable")

    started_wall = time.time()
    started_mono = time.monotonic()
    deadline = None if args.continuous else started_mono + float(hours) * 3600.0
    cycles = 0
    errors: list[str] = []
    cycle_summaries: list[dict[str, Any]] = []
    last_payload: dict[str, Any] | None = None

    try:
        while not STOP and (deadline is None or time.monotonic() < deadline):
            cycles += 1
            cycle_started = time.monotonic()
            try:
                payload = shadow.run_once(drive_upstream=True)
                last_payload = payload
                summary = _cycle_summary(payload)
                summary["cycle"] = cycles
                summary["runtime_sec"] = round(time.monotonic() - cycle_started, 3)
                summary["wall_ts"] = time.time()
                cycle_summaries.append(summary)
                # Keep the receipt bounded for long/multi-day runs.
                if len(cycle_summaries) > 500:
                    cycle_summaries = cycle_summaries[-500:]
                print(
                    "[P12] "
                    f"cycle={cycles} "
                    f"runtime={summary['runtime_sec']:.1f}s "
                    f"features={summary['features_examined']} "
                    f"eligible={summary['eligible']} "
                    f"diverged={summary['diverged']} "
                    f"frozen={summary['frozen']} "
                    f"twins_settled={summary['twins_settled']} "
                    f"status={summary['status']}",
                    flush=True,
                )
                if summary["organ_divergence"]:
                    print("[P12] divergence=" + json.dumps(summary["organ_divergence"], sort_keys=True), flush=True)
            except Exception as exc:
                msg = f"cycle_{cycles}:{type(exc).__name__}:{exc}"
                errors.append(msg)
                print("[P12] ERROR " + msg, flush=True)

            if STOP or (deadline is not None and time.monotonic() >= deadline):
                break
            sleep_for = pause
            if deadline is not None:
                sleep_for = min(sleep_for, max(0.0, deadline - time.monotonic()))
            until = time.monotonic() + sleep_for
            while not STOP and time.monotonic() < until:
                time.sleep(min(0.5, until - time.monotonic()))

        print("[P12] final settlement-only pass", flush=True)
        try:
            last_payload = shadow.run_once(drive_upstream=False)
        except Exception as exc:
            errors.append(f"final_settlement:{type(exc).__name__}:{exc}")

        receipt = {
            "schema": "hivenance_phase12_adaptive_gauntlet_v1",
            "started_ts": started_wall,
            "ended_ts": time.time(),
            "wall_clock_seconds": round(time.monotonic() - started_mono, 3),
            "continuous_requested": bool(args.continuous),
            "requested_hours": None if args.continuous else float(hours),
            "cycles_completed": cycles,
            "interrupted": bool(STOP),
            "census_path": str(args.census),
            "organ_runtime_control": control_plane,
            "runtime_mode_summary": _mode_summary(control_plane),
            "runtime_mode_enforcement": {
                "control_plane_loaded": True,
                "coordinator_handoff_present": True,
                "universal_legacy_organ_enforcement_complete": False,
                "note": "modes are canonical and exposed; organ-by-organ consumers are being wired progressively",
            },
            "recent_cycle_summaries": cycle_summaries,
            "cycle_errors": errors,
            "last_status": (last_payload or {}).get("status"),
            "execution_wired": False,
            "execution_eligible": False,
            "promotion_eligible": False,
            "private_exchange_access": False,
            "real_orders_submitted": 0,
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
        print("HIVENANCE_PHASE12_ADAPTIVE_GAUNTLET_RESULT")
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str), flush=True)
        return 0 if not errors else 2
    finally:
        _stop_agents(coordinator)


if __name__ == "__main__":
    raise SystemExit(main())
