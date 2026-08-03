#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.phoenix_authority import PhoenixAuthorityGuard, PROTECTED_ACTIONS


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def main() -> int:
    guard = PhoenixAuthorityGuard()
    snapshot = guard.snapshot()
    if snapshot.get("sole_live_order_authority") != "phase6_canary_operator":
        fail("Phase 6 is not the sole live-order authority")
    if snapshot.get("sole_scaling_authority") != "phase7_growth_governor":
        fail("Phase 7 is not the sole scaling authority")
    for component in snapshot.get("components", {}):
        for action in PROTECTED_ACTIONS:
            if guard.decision(component, action).allowed:
                fail(f"{component} unexpectedly allowed {action}")

    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    coordinator = (ROOT / "agents/coordinator.py").read_text(encoding="utf-8")
    config_agent = (ROOT / "agents/config_agent.py").read_text(encoding="utf-8")
    ui_source = (ROOT / "agents/ui_agent.py").read_text(encoding="utf-8")
    if "Legacy coordinator live execution is retired" not in main_source:
        fail("ordinary coordinator live retirement missing")
    for forbidden in ('current["stage"] = "tiny_live"', 'PUBLIC_BOT_AUTO_PROMOTED'):
        if forbidden in coordinator:
            fail(f"legacy promotion token remains: {forbidden}")
    if "legacy_arm_live_retired_use_phase6_operator" not in config_agent:
        fail("ARM LIVE retirement missing")
    if "Type ARM LIVE" in ui_source or "Legacy desktop resume is retired" not in ui_source:
        fail("desktop live/resume authority was not fully retired")

    for name in ("settings.yaml", "settings.live.yaml", "conservative_state.yaml", "conservative_headless_10m.yaml", "live_safe_1h.yaml"):
        path = ROOT / "config" / name
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for key in ("live_mode", "onchain_enabled", "public_bot_metrics_auto_promote", "hummingbot_sidecar_live_enabled", "market_making_quote_placement_enabled", "swarmguard_small_trade_bypass"):
            if bool(data.get(key, False)):
                fail(f"{name}: {key}=true")
        if not bool(data.get("dry_run", True)):
            fail(f"{name}: dry_run=false")
        if "tiny_live" in (data.get("promotion_allowed_stages") or []):
            fail(f"{name}: legacy tiny_live stage remains")

    print("PASS: Phase-7.1 integration authority reconciliation preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
