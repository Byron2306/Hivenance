from __future__ import annotations

import time
from typing import Any, Dict

from agents.config_agent import PHOENIX_FALSE_ONLY_FIELDS, PHOENIX_PROTECTED_FIELDS
from agents.phoenix_authority import PhoenixAuthorityGuard, PROTECTED_ACTIONS


PHASE0_SAFE_VALUES: Dict[str, Any] = {
    "phase0_quarantine": True,
    "dry_run": True,
    "live_mode": False,
    "onchain_enabled": False,
    "public_bot_metrics_auto_promote": False,
    "hummingbot_sidecar_live_enabled": False,
    "market_making_quote_placement_enabled": False,
    "openclaw_autonomy_enabled": False,
    "coin_selection_auto_switch": False,
    "swarmguard_small_trade_bypass": False,
    "volatility_harvest_enabled": False,
    "hummingbot_v2_leverage": 1,
}


def phase0_snapshot(cfg: Any, authority: PhoenixAuthorityGuard | None = None) -> Dict[str, Any]:
    authority = authority or PhoenixAuthorityGuard()
    controls: Dict[str, Dict[str, Any]] = {}
    violations: list[str] = []
    for key, expected in PHASE0_SAFE_VALUES.items():
        actual = getattr(cfg, key, expected)
        ok = actual == expected
        controls[key] = {"expected": expected, "actual": actual, "ok": ok}
        if not ok:
            violations.append(f"{key}: expected {expected!r}, got {actual!r}")

    protected_checks = {
        action: authority.decision("config_agent", action).to_dict()
        for action in sorted(PROTECTED_ACTIONS)
    }
    authority_locked = all(not item["allowed"] for item in protected_checks.values())

    return {
        "phase": 0,
        "name": "constitution_and_authority_lock",
        "ts": time.time(),
        "status": "LOCKED" if not violations and authority_locked else "VIOLATION",
        "quarantine_enabled": bool(getattr(cfg, "phase0_quarantine", True)),
        "controls": controls,
        "protected_actions": protected_checks,
        "protected_fields": sorted(PHOENIX_PROTECTED_FIELDS),
        "false_only_fields": sorted(PHOENIX_FALSE_ONLY_FIELDS),
        "violations": violations,
        "live_capital_permitted": False,
        "profit_mode": "research_governance_only",
        "exit_gate": {
            "signed_off": False,
            "required_future_operators": [
                "phase6_canary_operator",
                "phase7_growth_governor",
            ],
        },
    }
