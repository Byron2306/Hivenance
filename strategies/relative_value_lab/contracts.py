from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


RELATIVE_VALUE_AUTHORITY = "research_evidence_only_no_execution_or_promotion_authority"


@dataclass(frozen=True)
class PairRelationshipCrystal:
    schema: str
    pair_id: str
    base_symbol: str
    quote_symbol: str
    venue: str
    observed_at_ms: int
    lookback_seconds: int
    direct_route_available: bool
    relationship_method: str
    hedge_ratio: Optional[float] = None
    correlation: Optional[float] = None
    spread_definition: str = "log_price_difference"
    stationarity_score: Optional[float] = None
    mean_reversion_speed: Optional[float] = None
    half_life_seconds: Optional[float] = None
    structural_break_state: str = "UNKNOWN"
    stability_score: Optional[float] = None
    freshness_sec: Optional[float] = None
    evidence_root: Optional[str] = None
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelativeMarketState:
    schema: str
    pair_id: str
    timestamp_ms: int
    spread: Optional[float]
    spread_zscore: Optional[float]
    relative_return_1s_bps: Optional[float] = None
    relative_return_3s_bps: Optional[float] = None
    relative_return_10s_bps: Optional[float] = None
    relative_return_30s_bps: Optional[float] = None
    relative_volatility_bps: Optional[float] = None
    excursion_bps: Optional[float] = None
    order_flow_imbalance: Optional[float] = None
    aggressor_flow_delta: Optional[float] = None
    trade_intensity: Optional[float] = None
    bid_depth_usd: Optional[float] = None
    ask_depth_usd: Optional[float] = None
    depth_recovery_score: Optional[float] = None
    spread_cost_bps: Optional[float] = None
    route_cost_bps: Optional[float] = None
    horizon_context: Mapping[str, Any] = field(default_factory=dict)
    relationship_crystal_id: Optional[str] = None
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ForwardRelativeForecast:
    schema: str
    forecast_id: str
    pair_id: str
    timestamp_ms: int
    horizon_seconds: int
    model_id: str
    expected_relative_move_bps: Optional[float]
    prediction_lower_bps: Optional[float]
    prediction_upper_bps: Optional[float]
    probability_positive_gross: Optional[float]
    expected_cost_bps: Optional[float]
    expected_net_bps: Optional[float]
    uncertainty: Optional[float]
    calibration_state: str
    abstain: bool
    reason: str
    feature_digest: Optional[str] = None
    model_lineage: Mapping[str, Any] = field(default_factory=dict)
    inputs: Mapping[str, Any] = field(default_factory=dict)
    direction: str = "ABSTAIN"
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchCouncilReceipt:
    schema: str
    receipt_id: str
    created_at_ms: int
    subject_id: str
    adviser_model: str
    contradictions: tuple[str, ...] = field(default_factory=tuple)
    missing_evidence: tuple[str, ...] = field(default_factory=tuple)
    alternative_hypotheses: tuple[str, ...] = field(default_factory=tuple)
    analogous_slices: tuple[str, ...] = field(default_factory=tuple)
    suggested_falsification_tests: tuple[str, ...] = field(default_factory=tuple)
    explanation_confidence: Optional[float] = None
    raw_response_digest: Optional[str] = None
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)