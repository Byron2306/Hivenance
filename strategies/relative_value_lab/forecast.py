from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Optional

from .contracts import ForwardRelativeForecast, RelativeMarketState, RELATIVE_VALUE_AUTHORITY
from .pair_lab import PairDiagnostics


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OUForecastConfig:
    minimum_relationship_stability: float = 0.45
    minimum_net_edge_bps: float = 0.50
    uncertainty_multiplier: float = 1.96


class OUMeanReversionForecaster:
    """Transparent forward baseline for pair-relative mean reversion.

    The spread is defined by PairRelationshipLab as:
        log(A) - alpha - beta*log(B)

    Positive expected move means A is expected to outperform the hedged B leg.
    Negative expected move means B is expected to outperform A.

    This model is research-only. It cannot emit execution authority.
    """

    model_id = "relative_value_ou_mean_reversion_v1"

    def __init__(self, config: OUForecastConfig | None = None) -> None:
        self.config = config or OUForecastConfig()

    def forecast(
        self,
        *,
        state: RelativeMarketState,
        diagnostics: PairDiagnostics,
        horizon_seconds: int,
        expected_cost_bps: float,
        residual_sigma_bps_per_sqrt_sec: Optional[float] = None,
    ) -> ForwardRelativeForecast:
        horizon = max(1, int(horizon_seconds))
        cost = max(0.0, float(expected_cost_bps))
        reasons: list[str] = []

        if diagnostics.pair_id != state.pair_id:
            reasons.append("pair_identity_mismatch")
        if not diagnostics.eligible:
            reasons.append("relationship_not_eligible")
        if diagnostics.stability_score < self.config.minimum_relationship_stability:
            reasons.append("relationship_stability_below_floor")
        if state.spread is None:
            reasons.append("spread_unavailable")
        if diagnostics.ou_equilibrium is None:
            reasons.append("ou_equilibrium_unavailable")
        if diagnostics.ou_mean_reversion_speed_per_sec is None:
            reasons.append("ou_speed_unavailable")

        if reasons:
            return self._abstain(
                state=state,
                horizon_seconds=horizon,
                expected_cost_bps=cost,
                reasons=reasons,
            )

        current = float(state.spread)
        equilibrium = float(diagnostics.ou_equilibrium)
        kappa = max(0.0, float(diagnostics.ou_mean_reversion_speed_per_sec))
        attenuation = math.exp(-kappa * horizon)
        expected_future_spread = equilibrium + (current - equilibrium) * attenuation
        signed_move_bps = (expected_future_spread - current) * 10_000.0
        move_magnitude = abs(signed_move_bps)

        sigma = None
        lower = None
        upper = None
        probability = None
        if residual_sigma_bps_per_sqrt_sec is not None:
            per_root_sec = max(0.0, float(residual_sigma_bps_per_sqrt_sec))
            sigma = per_root_sec * math.sqrt(float(horizon))
            if sigma > 0:
                width = self.config.uncertainty_multiplier * sigma
                lower = signed_move_bps - width
                upper = signed_move_bps + width
                # Probability that the move in the forecasted direction is positive.
                probability = 0.5 * (1.0 + math.erf(move_magnitude / (sigma * math.sqrt(2.0))))

        net = move_magnitude - cost
        direction = (
            "LONG_A_SHORT_B" if signed_move_bps > 0
            else "LONG_B_SHORT_A" if signed_move_bps < 0
            else "ABSTAIN"
        )
        abstain = (
            direction == "ABSTAIN"
            or net < float(self.config.minimum_net_edge_bps)
        )
        reason = "ou_forecast_passed_cost_gate"
        if direction == "ABSTAIN":
            reason = "zero_expected_relative_move"
        elif net < float(self.config.minimum_net_edge_bps):
            reason = "insufficient_post_cost_forecast_edge"

        payload = {
            "pair_id": state.pair_id,
            "timestamp_ms": state.timestamp_ms,
            "horizon_seconds": horizon,
            "current_spread": current,
            "equilibrium": equilibrium,
            "kappa": kappa,
            "stability_score": diagnostics.stability_score,
            "expected_cost_bps": cost,
            "residual_sigma_bps_per_sqrt_sec": residual_sigma_bps_per_sqrt_sec,
        }
        return ForwardRelativeForecast(
            schema="hivenance_forward_relative_forecast_v1",
            forecast_id="rvf_" + _hash(payload)[:24],
            pair_id=state.pair_id,
            timestamp_ms=state.timestamp_ms,
            horizon_seconds=horizon,
            model_id=self.model_id,
            expected_relative_move_bps=round(signed_move_bps, 6),
            prediction_lower_bps=None if lower is None else round(lower, 6),
            prediction_upper_bps=None if upper is None else round(upper, 6),
            probability_positive_gross=None if probability is None else round(probability, 6),
            expected_cost_bps=round(cost, 6),
            expected_net_bps=round(net, 6),
            uncertainty=None if sigma is None else round(sigma, 6),
            calibration_state="STRUCTURAL_BASELINE_UNCALIBRATED",
            abstain=abstain,
            reason=reason,
            feature_digest=_hash(payload),
            model_lineage={
                "family": "ornstein_uhlenbeck_style",
                "relationship_method": "log_spread_ar1_ou_proxy",
                "training_mode": "closed_form_structural_baseline",
            },
            inputs={
                "spread": current,
                "spread_zscore": state.spread_zscore,
                "hedge_alpha": diagnostics.hedge_alpha,
                "hedge_ratio": diagnostics.hedge_ratio,
                "equilibrium": equilibrium,
                "mean_reversion_speed_per_sec": kappa,
                "half_life_seconds": diagnostics.half_life_seconds,
                "stability_score": diagnostics.stability_score,
            },
            direction=direction,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
        )

    def _abstain(
        self,
        *,
        state: RelativeMarketState,
        horizon_seconds: int,
        expected_cost_bps: float,
        reasons: list[str],
    ) -> ForwardRelativeForecast:
        payload = {
            "pair_id": state.pair_id,
            "timestamp_ms": state.timestamp_ms,
            "horizon_seconds": horizon_seconds,
            "reasons": reasons,
        }
        return ForwardRelativeForecast(
            schema="hivenance_forward_relative_forecast_v1",
            forecast_id="rvf_" + _hash(payload)[:24],
            pair_id=state.pair_id,
            timestamp_ms=state.timestamp_ms,
            horizon_seconds=horizon_seconds,
            model_id=self.model_id,
            expected_relative_move_bps=None,
            prediction_lower_bps=None,
            prediction_upper_bps=None,
            probability_positive_gross=None,
            expected_cost_bps=round(expected_cost_bps, 6),
            expected_net_bps=None,
            uncertainty=None,
            calibration_state="STRUCTURAL_BASELINE_UNAVAILABLE",
            abstain=True,
            reason=reasons[0] if reasons else "abstain",
            feature_digest=_hash(payload),
            model_lineage={"family": "ornstein_uhlenbeck_style"},
            inputs={"reasons": tuple(reasons)},
            direction="ABSTAIN",
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
        )