"""DEX-specific analogue of ``ResearchCostModel`` (see ``cost_model.py``).

``ResearchCostModel`` is deliberately CEX-shaped: its dominant cost term is
``taker_fee_bps_per_side`` (an exchange trading fee), with spread/impact as
secondary terms. DEX trades have a structurally different cost profile --
there is no exchange fee schedule, but every trade pays on-chain gas and
suffers AMM price impact / LP fee friction that is *already* measured for
us by ``DexMarginOracle``'s round-trip aggregator quote (``roundtrip_ratio``
is "how much of your notional do you get back after buying then immediately
selling", i.e. it already bakes in LP fees + slippage + price impact for
the probed size).

This module keeps the same result contract (``total_bps`` / ``tradable`` /
``reason``) so a Phase-3-style execution-lab gate can treat CEX and DEX cost
estimates uniformly, while using inputs that actually apply to on-chain
trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DexCostEstimate:
    roundtrip_friction_bps: float
    gas_bps: float
    latency_bps: float
    safety_bps: float
    total_bps: float
    tradable: bool
    reason: str = "ok"


class DexResearchCostModel:
    """Conservative DEX round-trip cost estimator.

    ``roundtrip_ratio`` and ``gas_usd`` come directly from
    ``DexMarginOracle.analyze_token()``'s ``quality`` dict -- both are real
    numbers measured from a live aggregator quote (1inch / ParaSwap /
    KyberSwap), not modeled assumptions.
    """

    def __init__(
        self,
        *,
        reference_notional_usd: float = 25.0,
        latency_buffer_bps: float = 2.0,
        safety_buffer_bps: float = 5.0,
        max_total_cost_bps: float = 300.0,
    ) -> None:
        self.reference_notional_usd = max(1.0, float(reference_notional_usd))
        self.latency_buffer_bps = max(0.0, float(latency_buffer_bps))
        self.safety_buffer_bps = max(0.0, float(safety_buffer_bps))
        self.max_total_cost_bps = max(1.0, float(max_total_cost_bps))

    def estimate(
        self,
        *,
        roundtrip_ratio: Optional[float],
        gas_usd: Optional[float],
        reference_notional_usd: Optional[float] = None,
    ) -> DexCostEstimate:
        notional = float(reference_notional_usd or self.reference_notional_usd)
        if roundtrip_ratio is None:
            return DexCostEstimate(
                roundtrip_friction_bps=0.0,
                gas_bps=0.0,
                latency_bps=self.latency_buffer_bps,
                safety_bps=self.safety_buffer_bps,
                total_bps=float("inf"),
                tradable=False,
                reason="quote_unavailable",
            )
        roundtrip_friction_bps = max(0.0, (1.0 - float(roundtrip_ratio)) * 10_000.0)
        gas_bps = 0.0
        if gas_usd is not None and notional > 0:
            gas_bps = max(0.0, (float(gas_usd) / notional) * 10_000.0)
        total_bps = roundtrip_friction_bps + gas_bps + self.latency_buffer_bps + self.safety_buffer_bps
        tradable = total_bps <= self.max_total_cost_bps
        return DexCostEstimate(
            roundtrip_friction_bps=round(roundtrip_friction_bps, 4),
            gas_bps=round(gas_bps, 4),
            latency_bps=self.latency_buffer_bps,
            safety_bps=self.safety_buffer_bps,
            total_bps=round(total_bps, 4),
            tradable=tradable,
            reason="ok" if tradable else "cost_exceeds_ceiling",
        )
