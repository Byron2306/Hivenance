#!/usr/bin/env python3
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> int:
    settings = yaml.safe_load((ROOT / "config/settings.yaml").read_text()) or {}
    for key in (
        "phase0_quarantine", "phase1_observation_enabled", "phase2_hypotheses_enabled",
        "phase3_execution_lab_enabled", "phase4_validation_enabled", "dry_run",
    ):
        if settings.get(key) is not True:
            fail(f"{key} must be true")
    for key in (
        "live_mode", "auto_trading_enabled", "onchain_enabled",
        "public_bot_metrics_auto_promote", "swarmguard_small_trade_bypass",
    ):
        if settings.get(key) is not False:
            fail(f"{key} must be false")
    if int(settings.get("hummingbot_v2_leverage", 0)) != 1:
        fail("hummingbot_v2_leverage must equal 1")
    if int(settings.get("phoenix_phase", 0)) < 4:
        fail("phoenix_phase must be at least 4")

    config = yaml.safe_load((ROOT / "config/volatility_breakout_phase4.yaml").read_text()) or {}
    for key in ("execution_wired", "private_exchange_access", "live_eligible"):
        if config.get(key) is not False:
            fail(f"{key} must remain false")
    if int(config.get("real_orders_submitted", -1)) != 0:
        fail("real_orders_submitted must equal zero")
    if config.get("human_review_required") is not True:
        fail("human_review_required must be true")

    research_files = [
        ROOT / "strategies/volatility_breakout/adversarial_validation.py",
        ROOT / "strategies/volatility_breakout/validation_lab.py",
    ]
    forbidden_modules = {
        "agents.execution", "agents.trade_executors", "ccxt", "binance.client",
        "krakenex", "web3",
    }
    forbidden_calls = {
        "create_order", "place_order", "submit_order", "market_buy", "market_sell",
        "create_market_buy_order", "create_market_sell_order",
    }
    for path in research_files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_modules:
                        fail(f"forbidden import {alias.name} in {path.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in forbidden_modules:
                    fail(f"forbidden import {module} in {path.name}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    name = ""
                if name in forbidden_calls:
                    fail(f"forbidden private execution call {name} in {path.name}")

    import sys
    sys.path.insert(0, str(ROOT))
    from agents.data_store_agent import DataStoreAgent
    db = DataStoreAgent(tempfile.mktemp(suffix=".db"))
    required_tables = {
        "phase4_validation_runs", "phase4_candidate_results", "phase4_fold_results",
        "phase4_holdout_results", "phase4_perturbation_results",
    }
    present = {
        row[0] for row in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing = required_tables - present
    if missing:
        fail(f"missing Phase-4 tables: {sorted(missing)}")

    print("PASS: Phoenix Phase-4 adversarial validation preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
