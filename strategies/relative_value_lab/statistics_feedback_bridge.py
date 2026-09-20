from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .statistical_synthesis import StatisticalEvidence


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def hypothesis_scope(
    *,
    model_id: str,
    symbol: str,
    horizon_seconds: int,
    regime: str = "unknown",
    scope_kind: str = "exact",
) -> str:
    return "|".join(
        (
            str(scope_kind),
            str(model_id),
            str(symbol),
            str(int(horizon_seconds)),
            str(regime or "unknown"),
        )
    )


def statistical_evidence_from_settlement(
    settlement: Any,
    *,
    regime: str = "unknown",
    scope_kind: str = "exact",
    evidence_root: str | None = None,
    weight: float = 1.0,
) -> StatisticalEvidence | None:
    """Convert a causally settled forecast into Statistics Bee evidence.

    Abstentions and settlements without a directional net result do not become
    performance samples. The evidence becomes available only at settlement time.
    """
    payload = settlement.to_dict() if hasattr(settlement, "to_dict") else dict(settlement)
    if bool(payload.get("abstain")):
        return None

    net = payload.get("realized_directional_net_bps")
    if net is None:
        net = payload.get("realized_net_bps")
    if net is None:
        return None

    forecast_id = str(payload.get("forecast_id") or payload.get("opportunity_id") or "unknown")
    model_id = str(payload.get("model_id") or payload.get("hypothesis_id") or "unknown")
    symbol = str(payload.get("pair_id") or payload.get("symbol") or "unknown")
    horizon = int(payload.get("horizon_seconds") or 0)
    forecast_ts = int(payload.get("forecast_timestamp_ms") or payload.get("timestamp_ms") or 0)
    settled_ts = int(payload.get("settled_timestamp_ms") or payload.get("target_timestamp_ms") or 0)

    if settled_ts <= forecast_ts:
        raise ValueError("statistics_feedback_settlement_not_future")

    root = str(evidence_root or _digest(payload))
    if not root.startswith("sha256:"):
        raise ValueError("statistics_feedback_root_unbound")

    return StatisticalEvidence(
        evidence_id=f"settled:{forecast_id}",
        scope=hypothesis_scope(
            model_id=model_id,
            symbol=symbol,
            horizon_seconds=horizon,
            regime=regime,
            scope_kind=scope_kind,
        ),
        observed_at_ms=forecast_ts,
        available_at_ms=settled_ts,
        realized_bps=float(net),
        positive=bool(float(net) > 0.0),
        evidence_root=root,
        weight=float(weight),
    )


def statistical_evidence_from_historical_outcome(
    outcome: Any,
    *,
    model_id: str,
    settled_at_ms: int,
    regime: str = "unknown",
    scope_kind: str = "exact",
    evidence_root: str | None = None,
) -> StatisticalEvidence | None:
    payload = outcome.to_dict() if hasattr(outcome, "to_dict") else dict(outcome)
    if bool(payload.get("abstain")):
        return None

    net = payload.get("realized_net_bps")
    if net is None:
        return None

    forecast_ts = int(payload.get("timestamp_ms") or 0)
    if int(settled_at_ms) <= forecast_ts:
        raise ValueError("statistics_feedback_historical_settlement_not_future")

    root = str(evidence_root or _digest(payload))
    return StatisticalEvidence(
        evidence_id="historical:" + _digest(
            {
                "model_id": model_id,
                "payload": payload,
                "settled_at_ms": int(settled_at_ms),
            }
        ).split(":", 1)[1][:24],
        scope=hypothesis_scope(
            model_id=str(model_id),
            symbol=str(payload.get("symbol") or "unknown"),
            horizon_seconds=int(payload.get("horizon_seconds") or 0),
            regime=regime,
            scope_kind=scope_kind,
        ),
        observed_at_ms=forecast_ts,
        available_at_ms=int(settled_at_ms),
        realized_bps=float(net),
        positive=bool(float(net) > 0.0),
        evidence_root=root,
        weight=1.0,
    )
