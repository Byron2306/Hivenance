from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class SimulatedOrderIntent:
    intent_id: str
    simulation_id: str
    forecast_id: str
    model_id: str
    venue: str
    symbol: str
    side: str
    order_policy: str
    scenario: str
    quantity: float
    notional_usd: float
    reference_price: float
    limit_price: Optional[float]
    risk_budget_usd: float
    stop_distance_bps: float
    horizon_seconds: int
    created_ts: float
    spot_executable: bool
    live_eligible: bool = False


@dataclass(frozen=True)
class SimulatedOrderEvent:
    sequence: int
    state: str
    ts: float
    reason: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulatedFill:
    fill_id: str
    leg: str
    side: str
    quantity: float
    price: float
    notional_usd: float
    fee_usd: float
    liquidity: str
    ts: float


@dataclass(frozen=True)
class CostAttribution:
    forecast_gross_bps: float
    market_gross_bps: float
    entry_spread_bps: float
    exit_spread_bps: float
    entry_impact_bps: float
    exit_impact_bps: float
    entry_latency_bps: float
    exit_latency_bps: float
    fee_bps: float
    missed_fill_opportunity_bps: float
    stop_slippage_bps: float
    total_cost_bps: float
    net_bps: float


@dataclass(frozen=True)
class SimulationResult:
    simulation_id: str
    run_id: str
    forecast_id: str
    model_id: str
    hypothesis: str
    venue: str
    symbol: str
    direction: str
    order_policy: str
    scenario: str
    fidelity: str
    seed: int
    status: str
    terminal_state: str
    started_ts: float
    completed_ts: float
    fill_ratio: float
    quantity_requested: float
    quantity_filled: float
    notional_requested_usd: float
    entry_reference_price: float
    exit_reference_price: float
    entry_fill_price: Optional[float]
    exit_fill_price: Optional[float]
    gross_return_bps: float
    net_return_bps: float
    profitable_after_costs: bool
    spot_executable: bool
    execution_wired: bool
    real_orders_submitted: int
    intent: SimulatedOrderIntent
    events: tuple[SimulatedOrderEvent, ...]
    fills: tuple[SimulatedFill, ...]
    costs: CostAttribution
    incidents: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
