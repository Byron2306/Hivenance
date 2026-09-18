#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> int:
    settings = yaml.safe_load((ROOT / "config/settings.yaml").read_text(encoding="utf-8")) or {}
    required = {
        "phase0_quarantine": True,
        "dry_run": True,
        "live_mode": False,
        "auto_trade_enabled": False,
        "onchain_enabled": False,
        "public_bot_metrics_auto_promote": False,
        "swarmguard_small_trade_bypass": False,
        "phase5_shadow_enabled": True,
        "phase5_human_approval_required": True,
        "phase5_parameter_freeze_required": True,
    }
    for key, expected in required.items():
        if settings.get(key) is not expected:
            fail(f"{key}={settings.get(key)!r}, expected {expected!r}")
    if int(settings.get("hummingbot_v2_leverage", 1)) != 1:
        fail("hummingbot_v2_leverage must equal 1")
    if int(settings.get("phoenix_phase", 0)) < 5:
        fail("phoenix_phase must be at least 5")

    shadow_files = [
        ROOT / "strategies/volatility_breakout/shadow_flight.py",
        ROOT / "strategies/volatility_breakout/shadow_lab.py",
        ROOT / "strategies/volatility_breakout/shadow_models.py",
        ROOT / "scripts/run_phase5_shadow_flight.py",
    ]
    forbidden = (
        "create_order", "create_market_order", "create_limit_order", "fetch_balance",
        "apiKey", "secret", "privatePost", "privateGet", "add_order",
    )
    for path in shadow_files:
        if not path.exists():
            fail(f"missing {path.relative_to(ROOT)}")
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lowered = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token.lower() in lowered:
                fail(f"forbidden private/execution token {token!r} in {path.relative_to(ROOT)}")

    profile = yaml.safe_load((ROOT / "config/volatility_breakout_phase5.yaml").read_text(encoding="utf-8")) or {}
    if profile.get("mode") != "public_shadow_only" or profile.get("execution_wired") is not False:
        fail("Phase-5 profile safety contract is invalid")
    if profile.get("private_exchange_access") is not False or int(profile.get("real_orders_submitted", -1)) != 0:
        fail("Phase-5 profile permits private access or orders")

    db = sqlite3.connect(":memory:")
    from agents.data_store_agent import DataStoreAgent
    store = DataStoreAgent(":memory:")
    tables = {row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required_tables = {
        "phase5_model_freezes", "phase5_shadow_runs", "phase5_shadow_intents", "phase5_shadow_settlements",
    }
    missing = required_tables - tables
    if missing:
        fail(f"missing Phase-5 tables: {sorted(missing)}")
    if store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] != 0:
        fail("live order table is not empty in clean preflight")
    print("PASS: Phase-5 shadow-flight safety and structure preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
