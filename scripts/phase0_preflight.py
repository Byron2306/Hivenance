#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SAFE = {
    "phase0_quarantine": True,
    "auto_trade_enabled": False,
    "dry_run": True,
    "live_mode": False,
    "kill_switch_enabled": True,
    "security_enabled": True,
    "onchain_enabled": False,
    "swarmguard_small_trade_bypass": False,
    "public_bot_metrics_auto_promote": False,
    "hummingbot_sidecar_live_enabled": False,
    "hummingbot_v2_leverage": 1,
    "market_making_quote_placement_enabled": False,
    "openclaw_autonomy_enabled": False,
    "coin_selection_auto_switch": False,
    "volatility_harvest_enabled": False,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-source", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []

    for rel in [
        "config/settings.yaml", "config/settings.live.yaml",
        "config/conservative_state.yaml", "config/conservative_headless_10m.yaml",
        "config/live_safe_1h.yaml",
    ]:
        data = yaml.safe_load((ROOT / rel).read_text()) or {}
        for key, expected in SAFE.items():
            if data.get(key) != expected:
                errors.append(f"{rel}: {key}={data.get(key)!r}, expected {expected!r}")
        if data.get("ui_host") != "127.0.0.1":
            errors.append(f"{rel}: ui_host must be 127.0.0.1")

    strategy = yaml.safe_load((ROOT / "config/volatility_breakout_phase0.yaml").read_text()) or {}
    if strategy.get("enabled") is not False or strategy.get("execution_wired") is not False:
        errors.append("volatility breakout scaffold is not quarantined")

    compose = (ROOT / "docker/docker-compose.yml").read_text()
    if "/var/run/docker.sock" in compose:
        errors.append("docker socket is mounted")
    if "CHANGE_ME" in compose:
        errors.append("docker compose contains CHANGE_ME fallback")

    if args.strict_source:
        forbidden_fallbacks = [
            ROOT / "buzzservice/service.py", ROOT / "swarmguard_service/service.py",
        ]
        for source in forbidden_fallbacks:
            if 'or "CHANGE_ME"' in source.read_text() or 'get("SWARMGUARD_HMAC_SECRET", "CHANGE_ME")' in source.read_text():
                errors.append(f"unsafe shared-secret fallback exists: {source.relative_to(ROOT)}")
        forbidden = ["config/api_keys.json", "config/api_keys.json.backup", "config/encryption.key"]
        for rel in forbidden:
            if (ROOT / rel).exists():
                errors.append(f"source-controlled secret material exists: {rel}")

    if errors:
        print("PHASE-0 PREFLIGHT: FAIL")
        for error in errors:
            print(f" - {error}")
        return 1
    print("PHASE-0 PREFLIGHT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
