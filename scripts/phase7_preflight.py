#!/usr/bin/env python3
from __future__ import annotations

import ast
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
        "phase7_growth_enabled": True,
        "phase7_stage_activation_enabled": False,
        "phase7_auto_demotion_enabled": True,
    }
    for key, expected in required.items():
        if settings.get(key) is not expected:
            fail(f"{key}={settings.get(key)!r}, expected {expected!r}")
    if int(settings.get("phoenix_phase", 0)) < 7:
        fail("phoenix_phase must be at least 7")
    if int(settings.get("hummingbot_v2_leverage", 1)) != 1:
        fail("leverage must remain 1x")
    if int(settings.get("phase7_max_stage", 99)) > 4:
        fail("default Phase-7 maximum stage may not exceed 4")
    notionals = [float(x) for x in (settings.get("phase7_stage_notional_caps_usd") or [])]
    if len(notionals) < 2 or notionals[0] != 5.0 or any(b < a for a, b in zip(notionals, notionals[1:])):
        fail("Phase-7 notional ladder must begin at USD 5 and increase monotonically")
    if max(notionals) > 25.0:
        fail("default controlled-growth ceiling may not exceed USD 25")
    if int(settings.get("phase7_min_new_round_trips", 0)) < 50:
        fail("each growth stage must require at least 50 new reconciled round trips")
    if int(settings.get("phase7_min_distinct_days", 0)) < 14:
        fail("each growth stage must require at least 14 distinct live days")
    if int(settings.get("phase7_proposal_cooldown_sec", 0)) < 3600:
        fail("default Phase-7 proposal cooling-off period must be at least one hour")

    required_files = [
        ROOT / "strategies/volatility_breakout/growth_models.py",
        ROOT / "strategies/volatility_breakout/growth_store.py",
        ROOT / "strategies/volatility_breakout/growth_lab.py",
        ROOT / "scripts/run_phase7_growth.py",
        ROOT / "scripts/phase7_synthetic_soak.py",
        ROOT / "config/volatility_breakout_phase7.yaml",
    ]
    for path in required_files:
        if not path.exists():
            fail(f"missing {path.relative_to(ROOT)}")
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    growth_text = (ROOT / "strategies/volatility_breakout/growth_lab.py").read_text(encoding="utf-8")
    runner_text = (ROOT / "scripts/run_phase7_growth.py").read_text(encoding="utf-8")
    for token in (
        "automatic_promotion\": False",
        "evaluate_demotion",
        "PHASE7_ENV_INTERLOCK",
        "stage_capped_config",
        "proposal cooling-off period",
    ):
        if token not in growth_text and token not in runner_text:
            fail(f"missing Phase-7 safety contract token: {token}")
    if "--live cannot be combined with --once" not in runner_text:
        fail("live Phase-7 single-cycle mode must remain forbidden")
    if "PHASE6_ACKNOWLEDGEMENT" not in runner_text or "--approve-next-entry" not in runner_text:
        fail("Phase-7 must preserve the per-entry Phase-6 human lease")
    if "HIVENANCE_KRAKEN_API_KEY" in growth_text or "HIVENANCE_KRAKEN_API_SECRET" in growth_text:
        fail("growth governor core must not load private exchange credentials")

    profile = yaml.safe_load((ROOT / "config/volatility_breakout_phase7.yaml").read_text(encoding="utf-8")) or {}
    if profile.get("mode") != "controlled_growth_governor_locked":
        fail("Phase-7 profile mode is invalid")
    if profile.get("phase7_stage_activation_enabled") is not False:
        fail("Phase-7 package must ship with stage activation disabled")
    if profile.get("phase6_live_submission_enabled") is not False:
        fail("Phase-7 package must ship with live submission disabled")
    if profile.get("desktop_arming_enabled") is not False or profile.get("operator_process_only") is not True:
        fail("growth authority must remain absent from the desktop")

    coordinator = (ROOT / "agents/coordinator.py").read_text(encoding="utf-8")
    ui = (ROOT / "agents/ui_agent.py").read_text(encoding="utf-8")
    renderer = (ROOT / "desktop-ui/renderer/app.js").read_text(encoding="utf-8")
    html = (ROOT / "desktop-ui/renderer/index.html").read_text(encoding="utf-8")
    if "def growth_snapshot" not in coordinator:
        fail("read-only coordinator growth projection is missing")
    if "activate_approved_stage(" in coordinator or "TinyLiveCanary(" in coordinator:
        fail("ordinary coordinator must not own Phase-7 or private canary authority")
    if '@self.app.route("/growth.json")' not in ui:
        fail("read-only Phase-7 endpoint is missing")
    if '@self.app.route("/growth.json", methods=' in ui:
        fail("Phase-7 desktop endpoint must expose GET only")
    if "loadGrowthData" not in renderer or "fetchAPI('/growth.json" not in renderer:
        fail("desktop growth governor projection is not wired")
    for forbidden in ("approve-growth", "activate-growth", "promote-stage", "resume-growth", "scale-now"):
        if forbidden in renderer.lower() or forbidden in html.lower():
            fail(f"desktop contains forbidden Phase-7 authority control: {forbidden}")
    if 'id="growth-view"' not in html or "NO DESKTOP ACTIVATION" not in html:
        fail("read-only growth governor view and safety statement are missing")

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
    for field in (
        "phase7_growth_enabled", "phase7_stage_activation_enabled", "phase7_max_stage",
        "phase7_allowed_symbols", "phase7_stage_notional_caps_usd", "phase7_auto_demotion_enabled",
    ):
        if field not in config_fields:
            fail(f"main Config is missing {field}")

    from agents.data_store_agent import DataStoreAgent
    from strategies.volatility_breakout.growth_store import GrowthStore
    store = DataStoreAgent(":memory:")
    GrowthStore(store)
    tables = {row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required_tables = {
        "phase7_growth_state", "phase7_growth_proposals", "phase7_growth_approvals",
        "phase7_growth_windows", "phase7_growth_incidents", "phase7_growth_audit",
    }
    missing = required_tables - tables
    if missing:
        fail(f"missing Phase-7 tables: {sorted(missing)}")
    if store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] != 0:
        fail("legacy live order table is not empty in clean preflight")
    print("PASS: Phase-7 controlled-growth governor, human promotion and automatic demotion preflight")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
