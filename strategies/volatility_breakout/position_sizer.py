from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionSize:
    notional_usd: float
    risk_budget_usd: float
    stop_distance_fraction: float
    executable: bool = False


class ResearchRiskBudgetSizer:
    """Calculates a research size while hard-coding execution to false."""

    def size(self, *, equity_usd: float, risk_fraction: float, stop_distance_fraction: float,
             sleeve_available_usd: float, depth_cap_usd: float) -> PositionSize:
        if equity_usd < 0 or sleeve_available_usd < 0 or depth_cap_usd < 0:
            raise ValueError("capital inputs must be non-negative")
        if not 0 < risk_fraction <= 0.001:
            raise ValueError("phase0 risk_fraction must be in (0, 0.001]")
        if stop_distance_fraction <= 0:
            raise ValueError("stop_distance_fraction must be positive")
        risk_budget = equity_usd * risk_fraction
        raw_notional = risk_budget / stop_distance_fraction
        notional = max(0.0, min(raw_notional, sleeve_available_usd, depth_cap_usd))
        return PositionSize(notional, risk_budget, stop_distance_fraction, executable=False)
