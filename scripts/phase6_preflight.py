#!/usr/bin/env python3
from __future__ import annotations

import ast
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
        "phase6_canary_enabled": True,
        "phase6_live_submission_enabled": False,
        "phase6_require_isolated_account": True,
    }
    for key, expected in required.items():
        if settings.get(key) is not expected:
            fail(f"{key}={settings.get(key)!r}, expected {expected!r}")
    if int(settings.get("phoenix_phase", 0)) < 6:
        fail("phoenix_phase must be at least 6")
    if int(settings.get("hummingbot_v2_leverage", 1)) != 1:
        fail("leverage must remain 1x")
    if float(settings.get("phase6_max_notional_usd", 999)) > 10.0:
        fail("default Phase-6 max notional may not exceed USD 10")
    if int(settings.get("phase6_max_entry_orders_per_approval", 0)) != 1:
        fail("each Phase-6 approval must permit exactly one entry")
    if int(settings.get("phase6_deadman_timeout_sec", 0)) < 15:
        fail("dead-man timeout is too short or disabled")
    symbols = settings.get("phase6_allowed_symbols") or []
    if not 1 <= len(symbols) <= 3:
        fail("Phase-6 default allowlist must contain one to three symbols")

    required_files = [
        ROOT / "strategies/volatility_breakout/canary_models.py",
        ROOT / "strategies/volatility_breakout/canary_store.py",
        ROOT / "strategies/volatility_breakout/canary_lab.py",
        ROOT / "strategies/volatility_breakout/kraken_canary.py",
        ROOT / "scripts/run_phase6_canary.py",
        ROOT / "scripts/phase6_synthetic_soak.py",
        ROOT / "config/volatility_breakout_phase6.yaml",
    ]
    for path in required_files:
        if not path.exists():
            fail(f"missing {path.relative_to(ROOT)}")
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    transport = (ROOT / "strategies/volatility_breakout/kraken_canary.py").read_text(encoding="utf-8")
    for forbidden in ("Withdraw", "WalletTransfer", "DepositAddress", "Earn/Allocate"):
        if forbidden in transport:
            fail(f"forbidden funding endpoint token present: {forbidden}")
    for required_endpoint in ("AddOrder", "OpenOrders", "QueryOrders", "Balance", "CancelAllOrdersAfter", "GetApiKeyInfo"):
        if required_endpoint not in transport:
            fail(f"missing required Kraken endpoint: {required_endpoint}")

    runner = (ROOT / "scripts/run_phase6_canary.py").read_text(encoding="utf-8")
    if "HIVENANCE_KRAKEN_API_KEY" not in runner or "HIVENANCE_KRAKEN_API_SECRET" not in runner:
        fail("runner must load credentials from environment only")
    if "--live cannot be combined with --once" not in runner:
        fail("live single-cycle operator mode must remain forbidden")
    if "operator_process_stopped_with_open_spot_inventory" not in runner:
        fail("operator shutdown must explicitly preserve EXIT_ONLY state for open inventory")
    if "HIVENANCE_PHASE6_LIVE_SUBMISSION" not in (ROOT / "strategies/volatility_breakout/canary_lab.py").read_text(encoding="utf-8"):
        fail("separate live environment interlock is missing")

    coordinator_text = (ROOT / "agents/coordinator.py").read_text(encoding="utf-8")
    ui_text = (ROOT / "agents/ui_agent.py").read_text(encoding="utf-8")
    renderer_text = (ROOT / "desktop-ui/renderer/app.js").read_text(encoding="utf-8")
    html_text = (ROOT / "desktop-ui/renderer/index.html").read_text(encoding="utf-8")
    if "def canary_snapshot" not in coordinator_text or '"tiny_live_canary": self.canary_snapshot' not in coordinator_text:
        fail("read-only coordinator canary projection is missing")
    if "TinyLiveCanary(" in coordinator_text:
        fail("ordinary coordinator must never construct Phase-6 private canary authority")
    if '@self.app.route("/canary.json")' not in ui_text:
        fail("read-only canary endpoint is missing")
    if '@self.app.route("/canary.json", methods=' in ui_text:
        fail("canary desktop endpoint must not expose write methods")
    if "loadCanaryData" not in renderer_text or "fetchAPI('/canary.json" not in renderer_text:
        fail("desktop canary flight deck is not wired")
    for forbidden_ui_token in ("approve-canary", "arm-canary", "submit-canary", "resume-canary"):
        if forbidden_ui_token in renderer_text.lower() or forbidden_ui_token in html_text.lower():
            fail(f"desktop contains forbidden Phase-6 authority control: {forbidden_ui_token}")
    if 'id="canary-view"' not in html_text or "DESKTOP ARMING" not in html_text:
        fail("read-only canary view and safety statement are missing")

    main_tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"), filename="main.py")
    config_fields = []
    config_calls = []
    for node in main_tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            config_fields = [item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)]
    for node in ast.walk(main_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Config":
            config_calls.append([kw.arg for kw in node.keywords if kw.arg])
    if not config_calls or set(config_fields) != set(config_calls[0]):
        fail("main Config constructor does not match the typed configuration contract")
    for field in ("phase6_canary_enabled", "phase6_live_submission_enabled", "phase6_max_notional_usd", "phase6_daily_loss_halt_usd"):
        if field not in config_fields:
            fail(f"main Config is missing {field}")

    profile = yaml.safe_load((ROOT / "config/volatility_breakout_phase6.yaml").read_text(encoding="utf-8")) or {}
    if profile.get("mode") != "tiny_live_canary_disarmed":
        fail("Phase-6 profile mode is invalid")
    if profile.get("desktop_arming_enabled") is not False or profile.get("operator_process_only") is not True:
        fail("desktop arming must remain absent and the canary must be operator-process-only")

    from agents.data_store_agent import DataStoreAgent
    from strategies.volatility_breakout.canary_store import CanaryStore
    store = DataStoreAgent(":memory:")
    CanaryStore(store)
    tables = {row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required_tables = {
        "phase6_canary_state", "phase6_canary_approvals", "phase6_canary_runs",
        "phase6_canary_intents", "phase6_canary_orders", "phase6_canary_positions",
        "phase6_canary_incidents", "phase6_canary_reconciliations", "phase6_deadman_heartbeats",
    }
    missing = required_tables - tables
    if missing:
        fail(f"missing Phase-6 tables: {sorted(missing)}")
    if store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] != 0:
        fail("legacy live order table is not empty in clean preflight")
    print("PASS: Phase-6 isolated tiny-live canary safety and structure preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
