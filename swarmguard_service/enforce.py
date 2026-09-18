from __future__ import annotations

from typing import Any, Dict, List, Tuple


def enforce(
    rules: Dict[str, Any],
    council: Dict[str, Any],
    oracle: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], List[str]]:
    reasons: List[str] = []

    if not council:
        return False, {}, ["NO_COUNCIL_DECISION"]
    if not oracle:
        return False, {}, ["NO_ORACLE_REGIME"]

    regime = str(oracle.get("name") or oracle.get("regime") or "").upper()
    caps = rules.get("regime_caps", {}).get(regime)
    if not caps:
        return False, {}, ["UNKNOWN_REGIME"]

    th = rules.get("svs_thresholds", {})
    score = float(council.get("score", 0.0))
    margin = float(council.get("margin", 0.0))
    distinct = int(council.get("distinct_workers", 0))
    rec = str(council.get("recommendation", "REJECT"))

    if score < float(th.get("reject_below", 0.0)):
        return False, {}, ["SVS_SCORE_TOO_LOW"]
    if margin < float(th.get("min_margin", 0.0)):
        return False, {}, ["SVS_MARGIN_TOO_LOW"]
    if distinct < int(th.get("min_distinct_workers", 0)):
        return False, {}, ["NOT_ENOUGH_WORKER_DIVERSITY"]

    allowed = caps.get("allowed_recommendations", [])
    if rec not in allowed:
        return False, {}, ["RECOMMENDATION_BLOCKED_BY_REGIME"]

    permit = {
        "max_position_pct": caps.get("max_position_pct"),
        "max_notional_usdt": caps.get("max_notional_usdt"),
        "max_slippage_bps": caps.get("max_slippage_bps"),
        "cooldown_secs": caps.get("cooldown_secs"),
        "order_type": council.get("risk_hints", {}).get("order_type", "LIMIT"),
        "ttl_secs": council.get("risk_hints", {}).get("ttl_secs", 120),
    }
    reasons += ["SVS_OK", "REGIME_OK", "LIMITS_APPLIED"]
    return True, permit, reasons
