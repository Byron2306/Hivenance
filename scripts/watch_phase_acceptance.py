#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from urllib.error import URLError
from urllib.request import urlopen


PHASE_ENDPOINTS = {
    1: "/observation.json?limit=1&compact=1",
    2: "/hypotheses.json?limit=1&compact=1",
    3: "/execution_lab.json?limit=1&compact=1",
    4: "/validation_lab.json?limit=1&compact=1",
    5: "/shadow_flight.json?limit=1&compact=1",
}


def fetch_json(base_url: str, endpoint: str) -> dict:
    with urlopen(f"{base_url.rstrip('/')}{endpoint}", timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def gate_line(phase: int, payload: dict) -> str:
    gate = payload.get("dio_gate") if isinstance(payload.get("dio_gate"), dict) else {}
    if phase == 1:
        readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
        ready = bool(readiness.get("ready_for_phase2_review"))
        reasons = [str(reason).replace("_", " ") for reason in readiness.get("reasons") or []]
        detail = "; ".join(reasons[:4]) if reasons else "all predicates passed"
        runs = int(readiness.get("runs") or 0)
        healthy = int(readiness.get("healthy_runs") or 0)
        ratio = 100.0 * float(readiness.get("run_success_ratio") or 0.0)
        buckets = int(readiness.get("distinct_snapshot_buckets") or 0)
        required_buckets = int(readiness.get("required_distinct_snapshots") or 0)
        window = readiness.get("evidence_window_hours")
        progress = (
            f"health={healthy}/{runs} ({ratio:.1f}%) "
            f"hourly_buckets={buckets}/{required_buckets} window={window:g}h"
            if window is not None else f"health={healthy}/{runs} ({ratio:.1f}%)"
        )
        return f"Phase 1: {'PASS' if ready else 'REFUSE'} | {progress} | {detail}"
    decision = str(gate.get("decision") or "UNAVAILABLE")
    marker = "PASS" if decision == "ALLOW" else decision
    reasons = [str(reason).replace("_", " ") for reason in gate.get("reasons") or []]
    detail = "; ".join(reasons[:4]) if reasons else "all predicates passed"
    computed_ts = float(gate.get("computed_ts") or 0.0)
    age = f" snapshot_age={max(0, int(time.time() - computed_ts))}s" if computed_ts else ""
    return f"Phase {phase}: {marker}{age} | {detail}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch persisted Hivenance phase-acceptance decisions")
    parser.add_argument("--base-url", default="http://127.0.0.1:5001")
    parser.add_argument("--interval-sec", type=float, default=10.0)
    parser.add_argument("--heartbeat-sec", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    previous = None
    last_printed = 0.0
    while True:
        lines = []
        for phase, endpoint in PHASE_ENDPOINTS.items():
            try:
                lines.append(gate_line(phase, fetch_json(args.base_url, endpoint)))
            except (OSError, URLError, ValueError, json.JSONDecodeError) as exc:
                lines.append(f"Phase {phase}: OFFLINE | {type(exc).__name__}")
        snapshot = "\n".join(lines)
        now = time.monotonic()
        heartbeat_due = now - last_printed >= max(10.0, float(args.heartbeat_sec or 60.0))
        if snapshot != previous or args.once or heartbeat_due:
            print(f"\n[{datetime.now().isoformat(timespec='seconds')}] acceptance update", flush=True)
            print(snapshot, flush=True)
            previous = snapshot
            last_printed = now
        if args.once:
            return 0
        time.sleep(max(2.0, float(args.interval_sec or 10.0)))


if __name__ == "__main__":
    raise SystemExit(main())
