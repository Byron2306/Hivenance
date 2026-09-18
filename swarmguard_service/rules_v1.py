from __future__ import annotations

import json
import os
from typing import Any, Dict


_DEFAULT_RULES: Dict[str, Any] = {
    "svs_thresholds": {
        "reject_below": 0.55,
        "small_from": 0.55,
        "normal_from": 0.70,
        "scale_from": 0.82,
        "min_margin": 0.15,
        "min_distinct_workers": 2,
    },
    "regime_caps": {
        "CHAOTIC": {
            "max_position_pct": 0.02,
            "max_notional_usdt": 75,
            "max_slippage_bps": 15,
            "cooldown_secs": 300,
            "allowed_recommendations": ["ALLOW_SMALL"],
        },
        "TRENDING": {
            "max_position_pct": 0.08,
            "max_notional_usdt": 300,
            "max_slippage_bps": 25,
            "cooldown_secs": 60,
            "allowed_recommendations": ["ALLOW_SMALL", "ALLOW_NORMAL", "ALLOW_SCALE"],
        },
        "RANGING": {
            "max_position_pct": 0.06,
            "max_notional_usdt": 200,
            "max_slippage_bps": 20,
            "cooldown_secs": 90,
            "allowed_recommendations": ["ALLOW_SMALL", "ALLOW_NORMAL"],
        },
    },
    "buzz_staking": {
        "ALLOW_SMALL": 5,
        "ALLOW_NORMAL": 12,
        "ALLOW_SCALE": 25,
        "OVERRIDE": 60,
    },
}


def load_rules(path: str | None = None) -> Dict[str, Any]:
    rules_path = path or os.environ.get("SWARMGUARD_RULES_PATH") or "config/swarmguard_rules_v1.json"
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_RULES)
