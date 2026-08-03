from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import FeatureVector


@dataclass(frozen=True)
class CostEstimate:
    fee_bps: float
    spread_bps: float
    impact_bps: float
    latency_bps: float
    safety_bps: float
    total_bps: float
    tradable: bool
    reason: str = "ok"


class ResearchCostModel:
    """Conservative pre-trade cost estimator for Phase-2 hypothesis scoring.

    This model is intentionally simple and inspectable. It never authorizes an
    order. It estimates the cost hurdle that a hypothesis must beat in research.
    """

    def __init__(
        self,
        *,
        taker_fee_bps_per_side: float = 10.0,
        reference_notional_usd: float = 5.0,
        latency_buffer_bps: float = 2.0,
        safety_buffer_bps: float = 3.0,
        max_impact_bps: float = 50.0,
        max_total_cost_bps: float = 150.0,
    ) -> None:
        self.taker_fee_bps_per_side = max(0.0, float(taker_fee_bps_per_side))
        self.reference_notional_usd = max(0.01, float(reference_notional_usd))
        self.latency_buffer_bps = max(0.0, float(latency_buffer_bps))
        self.safety_buffer_bps = max(0.0, float(safety_buffer_bps))
        self.max_impact_bps = max(0.0, float(max_impact_bps))
        self.max_total_cost_bps = max(1.0, float(max_total_cost_bps))

    def estimate(self, features: FeatureVector) -> CostEstimate:
        if features.spread_bps is None:
            return CostEstimate(0, 0, 0, 0, 0, 0, False, "spread_unavailable")
        if features.depth_usd_25bps is None or features.depth_usd_25bps <= 0:
            return CostEstimate(0, float(features.spread_bps), 0, 0, 0, 0, False, "depth_unavailable")

        fee = self.taker_fee_bps_per_side * 2.0
        spread = max(0.0, float(features.spread_bps))
        participation = self.reference_notional_usd / max(float(features.depth_usd_25bps), self.reference_notional_usd)
        # Square-root impact is a deliberately conservative small-notional proxy.
        impact = min(self.max_impact_bps, 25.0 * (participation ** 0.5))
        latency = self.latency_buffer_bps
        safety = self.safety_buffer_bps
        total = fee + spread + impact + latency + safety
        tradable = total <= self.max_total_cost_bps
        return CostEstimate(
            fee_bps=round(fee, 6),
            spread_bps=round(spread, 6),
            impact_bps=round(impact, 6),
            latency_bps=round(latency, 6),
            safety_bps=round(safety, 6),
            total_bps=round(total, 6),
            tradable=tradable,
            reason="ok" if tradable else "cost_above_research_ceiling",
        )
