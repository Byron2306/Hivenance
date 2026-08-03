from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class CanaryApproval:
    approval_id: str
    freeze_id: str
    phase4_run_id: str
    candidate_key: str
    model_id: str
    order_policy: str
    approved_by: str
    approved_ts: float
    expires_ts: float
    allowed_symbols: tuple[str, ...]
    max_notional_usd: float
    max_entry_orders: int
    config_hash: str
    acknowledgement_hash: str
    live_submission_authorized: bool
    status: str = "ACTIVE"
    automatic_scaling: bool = False
    leverage: int = 1

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_symbols"] = list(self.allowed_symbols)
        return payload


@dataclass(frozen=True)
class CanaryIntent:
    canary_intent_id: str
    shadow_intent_id: str
    forecast_id: str
    approval_id: str
    freeze_id: str
    client_order_id: str
    venue: str
    symbol: str
    side: str
    order_type: str
    time_in_force: str
    quantity: float
    notional_usd: float
    reference_price: float
    limit_price: float
    stop_price: float
    target_price: float
    horizon_ts: float
    predicted_cost_bps: float
    predicted_net_bps: float
    probability_positive_net: float
    data_quality: float
    spread_bps: float
    created_ts: float
    deadline_rfc3339: str
    config_hash: str
    live_submission_requested: bool
    validate_only_completed: bool = False
    status: str = "PERSISTED"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanaryOrder:
    client_order_id: str
    canary_intent_id: str
    exchange_order_id: Optional[str]
    symbol: str
    side: str
    status: str
    quantity: float
    limit_price: float
    filled_quantity: float
    average_fill_price: Optional[float]
    cost_quote: float
    fee_quote: float
    created_ts: float
    updated_ts: float
    raw_status: Optional[str] = None
    live_submitted: bool = False
    reconciled: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanaryPosition:
    position_id: str
    entry_client_order_id: str
    symbol: str
    quantity: float
    entry_price: float
    entry_cost_quote: float
    opened_ts: float
    stop_price: float
    target_price: float
    horizon_ts: float
    status: str = "OPEN"
    exit_client_order_id: Optional[str] = None
    exit_price: Optional[float] = None
    closed_ts: Optional[float] = None
    realized_pnl_quote: Optional[float] = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanaryIncident:
    incident_id: str
    ts: float
    severity: str
    category: str
    message: str
    symbol: Optional[str] = None
    client_order_id: Optional[str] = None
    requires_human_review: bool = True
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
