#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> int:
    settings = yaml.safe_load((ROOT / "config/settings.yaml").read_text()) or {}
    required_true = ["phase0_quarantine", "phase1_observation_enabled", "phase2_hypotheses_enabled", "dry_run"]
    for key in required_true:
        if settings.get(key) is not True:
            fail(f"{key} must be true")
    required_false = ["live_mode", "auto_trading_enabled", "onchain_enabled", "public_bot_metrics_auto_promote", "swarmguard_small_trade_bypass"]
    for key in required_false:
        if settings.get(key) is not False:
            fail(f"{key} must be false")
    if int(settings.get("hummingbot_v2_leverage", 0)) != 1:
        fail("hummingbot_v2_leverage must equal 1")
    if int(settings.get("phoenix_phase", 0)) < 2:
        fail("phoenix_phase must be at least 2")

    research_files = [
        ROOT / "strategies/volatility_breakout/hypothesis_models.py",
        ROOT / "strategies/volatility_breakout/hypothesis_competition.py",
        ROOT / "strategies/volatility_breakout/hypothesis_swarm.py",
    ]
    forbidden_modules = {"agents.execution", "agents.trade_executors", "ccxt", "binance.client"}
    forbidden_calls = {"create_order", "place_order", "submit_order", "market_buy", "market_sell"}
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
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in forbidden_calls:
                    fail(f"forbidden execution call {name} in {path.name}")

    config = yaml.safe_load((ROOT / "config/volatility_breakout_phase2.yaml").read_text()) or {}
    if config.get("execution_wired") is not False or config.get("live_eligible") is not False:
        fail("Phase-2 strategy config must remain non-executable")
    if int(config.get("orders_submitted", -1)) != 0:
        fail("Phase-2 orders_submitted must equal zero")

    print("PASS: Phoenix Phase-2 hypothesis research preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
