from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class ShadowFreeze:
    freeze_id: str
    phase4_run_id: str
    candidate_key: str
    model_id: str
    order_policy: str
    approved_by: str
    approved_ts: float
    phase4_dataset_hash: str
    config_hash: str
    status: str = "ACTIVE"
    shadow_only: bool = True
    execution_eligible: bool = False


@dataclass(frozen=True)
class ShadowOrderIntent:
    shadow_intent_id: str
    forecast_id: str
    freeze_id: str
    phase4_run_id: str
    candidate_key: str
    model_id: str
    order_policy: str
    venue: str
    symbol: str
    direction: str
    side: str
    order_type: str
    time_in_force: str
    quantity: float
    notional_usd: float
    reference_price: float
    limit_price: Optional[float]
    stop_distance_bps: float
    risk_budget_usd: float
    predicted_move_bps: float
    predicted_cost_bps: float
    predicted_net_bps: float
    probability_positive_net: float
    horizon_seconds: int
    created_ts: float
    target_ts: float
    data_quality: float
    spread_bps: float
    depth_usd_25bps: float
    venue_profile_version: str
    config_hash: str
    transmission_status: str = "NEVER_TRANSMITTED"
    private_endpoint_called: bool = False
    credentials_used: bool = False
    live_eligible: bool = False
    execution_wired: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ShadowSettlement:
    settlement_id: str
    shadow_intent_id: str
    forecast_id: str
    settled_ts: float
    status: str
    fill_model: str
    fill_ratio: float
    intended_entry_price: float
    hypothetical_entry_price: Optional[float]
    reference_exit_price: Optional[float]
    hypothetical_exit_price: Optional[float]
    entry_slippage_bps: float
    exit_slippage_bps: float
    fee_bps: float
    impact_bps: float
    observed_total_cost_bps: float
    predicted_cost_bps: float
    cost_error_bps: float
    gross_directional_return_bps: float
    net_return_bps: float
    profitable_after_costs: bool
    data_quality: float
    transmission_attempted: bool = False
    real_orders_submitted: int = 0
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
