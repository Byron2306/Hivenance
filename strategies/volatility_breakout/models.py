from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass(frozen=True)
class CandidateObservation:
    symbol: str
    venue: str
    timestamp_ms: int
    price: Optional[float]
    quote_volume_24h: Optional[float]
    spread_bps: Optional[float]
    depth_usd_25bps: Optional[float]
    listing_age_days: Optional[float]
    venue_count: int
    data_quality: float
    freshness_sec: Optional[float] = None
    continuity_ratio: Optional[float] = None
    score: float = 0.0
    eligible: bool = False
    observation_eligible: bool = False
    execution_eligible: bool = False
    rejection_reasons: tuple[str, ...] = field(default_factory=tuple)
    values: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureVector:
    symbol: str
    timestamp_ms: int
    price: Optional[float]
    realized_volatility_fast: Optional[float]
    realized_volatility_baseline: Optional[float]
    volatility_expansion: Optional[float]
    volume_zscore: Optional[float]
    trade_count_zscore: Optional[float]
    order_flow_imbalance: Optional[float]
    book_imbalance: Optional[float]
    spread_bps: Optional[float]
    depth_usd_25bps: Optional[float]
    quote_volume_24h: Optional[float]
    return_5: Optional[float]
    freshness_sec: Optional[float]
    continuity_ratio: Optional[float]
    data_quality: float
    values: Mapping[str, object] = field(default_factory=dict)
    complete: bool = False

    # Phase-2 research features. They remain Optional so older Phase-1 evidence
    # can still be loaded without inventing replacement values.
    return_zscore: Optional[float] = None
    price_zscore: Optional[float] = None
    range_position: Optional[float] = None
    trend_slope: Optional[float] = None
    atr_pct: Optional[float] = None
    reversal_return_1: Optional[float] = None
    momentum_consistency: Optional[float] = None
    volume_ratio: Optional[float] = None


@dataclass(frozen=True)
class Forecast:
    symbol: str
    timestamp_ms: int
    horizon_seconds: int
    direction: str = "ABSTAIN"
    probability_positive_net: Optional[float] = None
    expected_move_bps: Optional[float] = None
    expected_cost_bps: Optional[float] = None
    expected_net_bps: Optional[float] = None
    abstain: bool = True
    reason: str = "phase1_observation_only"

    # Phase-2 provenance and uncertainty fields.
    model_id: str = "observation_only"
    hypothesis: str = "observation"
    raw_score: Optional[float] = None
    uncertainty: Optional[float] = None
    calibration_state: str = "UNAVAILABLE"
    feature_version: str = "phase1.v1"
    reasons: tuple[str, ...] = field(default_factory=tuple)
    inputs: Mapping[str, object] = field(default_factory=dict)
    execution_eligible: bool = False


@dataclass(frozen=True)
class ObservationRunSummary:
    run_id: str
    venue: str
    started_at_ms: int
    completed_at_ms: int
    symbols_attempted: int
    symbols_successful: int
    symbols_eligible: int
    mean_data_quality: float
    errors: tuple[str, ...] = field(default_factory=tuple)
    execution_wired: bool = False
    orders_submitted: int = 0


@dataclass(frozen=True)
class HypothesisRunSummary:
    run_id: str
    observation_run_id: str
    venue: str
    started_at_ms: int
    completed_at_ms: int
    symbols_evaluated: int
    forecasts_total: int
    non_abstain_forecasts: int
    abstentions: int
    primary_models: tuple[str, ...] = field(default_factory=tuple)
    federated_models: tuple[str, ...] = field(default_factory=tuple)
    baseline_models: tuple[str, ...] = field(default_factory=tuple)
    execution_wired: bool = False
    orders_submitted: int = 0
