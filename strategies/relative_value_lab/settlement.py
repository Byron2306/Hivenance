from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .contracts import ForwardRelativeForecast, RelativeMarketState, RELATIVE_VALUE_AUTHORITY


@dataclass(frozen=True)
class SettledRelativeForecast:
    schema: str
    forecast_id: str
    pair_id: str
    model_id: str
    forecast_timestamp_ms: int
    target_timestamp_ms: int
    settled_timestamp_ms: int
    horizon_seconds: int
    direction: str
    entry_spread: float
    settled_spread: float
    predicted_signed_move_bps: float | None
    realized_signed_move_bps: float
    realized_directional_gross_bps: float | None
    expected_cost_bps: float | None
    realized_directional_net_bps: float | None
    forecast_error_bps: float | None
    abstain: bool
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _Anchor:
    forecast: ForwardRelativeForecast
    entry_spread: float
    hedge_alpha: float | None = None
    hedge_ratio: float | None = None


class ProspectiveForecastSettler:
    """Settle frozen forecasts only after their declared future horizon."""

    def __init__(self) -> None:
        self._anchors: dict[str, _Anchor] = {}
        self._settled: set[str] = set()

    def register(
        self,
        *,
        forecast: ForwardRelativeForecast,
        state: RelativeMarketState,
    ) -> None:
        if forecast.forecast_id in self._anchors:
            raise ValueError(f"forecast already registered: {forecast.forecast_id}")
        if forecast.pair_id != state.pair_id:
            raise ValueError("forecast/state pair mismatch")
        if forecast.timestamp_ms != state.timestamp_ms:
            raise ValueError("forecast/state timestamp mismatch")
        if state.spread is None:
            raise ValueError("entry spread unavailable")
        hedge_alpha = forecast.inputs.get("hedge_alpha") if forecast.inputs else None
        hedge_ratio = forecast.inputs.get("hedge_ratio") if forecast.inputs else None
        self._anchors[forecast.forecast_id] = _Anchor(
            forecast=forecast,
            entry_spread=float(state.spread),
            hedge_alpha=None if hedge_alpha is None else float(hedge_alpha),
            hedge_ratio=None if hedge_ratio is None else float(hedge_ratio),
        )

    def pending(self) -> int:
        return len(self._anchors) - len(self._settled)


    def settle_prices(
        self,
        *,
        pair_id: str,
        timestamp_ms: int,
        price_a: float,
        price_b: float,
    ) -> list[SettledRelativeForecast]:
        """Settle against future raw prices under each forecast's frozen hedge.

        This avoids re-fitting the relationship at settlement time. Forecasts
        without frozen hedge parameters are skipped here and may still be
        settled through settle(RelativeMarketState) for backward compatibility.
        """
        pa = float(price_a)
        pb = float(price_b)
        if pa <= 0.0 or pb <= 0.0:
            return []

        out: list[SettledRelativeForecast] = []
        for forecast_id, anchor in list(self._anchors.items()):
            if forecast_id in self._settled:
                continue
            forecast = anchor.forecast
            if forecast.pair_id != str(pair_id):
                continue
            target_ms = forecast.timestamp_ms + int(forecast.horizon_seconds) * 1000
            if int(timestamp_ms) < target_ms:
                continue
            if anchor.hedge_alpha is None or anchor.hedge_ratio is None:
                continue

            settled_spread = (
                math.log(pa)
                - float(anchor.hedge_alpha)
                - float(anchor.hedge_ratio) * math.log(pb)
            )
            realized_signed = (settled_spread - anchor.entry_spread) * 10_000.0
            direction_sign = (
                1.0 if forecast.direction == "LONG_A_SHORT_B"
                else -1.0 if forecast.direction == "LONG_B_SHORT_A"
                else None
            )
            directional_gross = (
                None if direction_sign is None
                else direction_sign * realized_signed
            )
            directional_net = None
            if directional_gross is not None and forecast.expected_cost_bps is not None:
                directional_net = directional_gross - float(forecast.expected_cost_bps)

            error = None
            if forecast.expected_relative_move_bps is not None:
                error = realized_signed - float(forecast.expected_relative_move_bps)

            settled = SettledRelativeForecast(
                schema="hivenance_settled_relative_forecast_v1",
                forecast_id=forecast.forecast_id,
                pair_id=forecast.pair_id,
                model_id=forecast.model_id,
                forecast_timestamp_ms=forecast.timestamp_ms,
                target_timestamp_ms=target_ms,
                settled_timestamp_ms=int(timestamp_ms),
                horizon_seconds=forecast.horizon_seconds,
                direction=forecast.direction,
                entry_spread=anchor.entry_spread,
                settled_spread=settled_spread,
                predicted_signed_move_bps=forecast.expected_relative_move_bps,
                realized_signed_move_bps=realized_signed,
                realized_directional_gross_bps=directional_gross,
                expected_cost_bps=forecast.expected_cost_bps,
                realized_directional_net_bps=directional_net,
                forecast_error_bps=error,
                abstain=forecast.abstain,
                authority=RELATIVE_VALUE_AUTHORITY,
                execution_eligible=False,
            )
            self._settled.add(forecast_id)
            out.append(settled)
        return out

    def settle(self, state: RelativeMarketState) -> list[SettledRelativeForecast]:
        if state.spread is None:
            return []
        out: list[SettledRelativeForecast] = []
        for forecast_id, anchor in list(self._anchors.items()):
            if forecast_id in self._settled:
                continue
            forecast = anchor.forecast
            if forecast.pair_id != state.pair_id:
                continue
            target_ms = forecast.timestamp_ms + int(forecast.horizon_seconds) * 1000
            if state.timestamp_ms < target_ms:
                continue

            realized_signed = (float(state.spread) - anchor.entry_spread) * 10_000.0
            direction_sign = (
                1.0 if forecast.direction == "LONG_A_SHORT_B"
                else -1.0 if forecast.direction == "LONG_B_SHORT_A"
                else None
            )
            directional_gross = (
                None if direction_sign is None
                else direction_sign * realized_signed
            )
            directional_net = None
            if directional_gross is not None and forecast.expected_cost_bps is not None:
                directional_net = directional_gross - float(forecast.expected_cost_bps)

            error = None
            if forecast.expected_relative_move_bps is not None:
                error = realized_signed - float(forecast.expected_relative_move_bps)

            settled = SettledRelativeForecast(
                schema="hivenance_settled_relative_forecast_v1",
                forecast_id=forecast.forecast_id,
                pair_id=forecast.pair_id,
                model_id=forecast.model_id,
                forecast_timestamp_ms=forecast.timestamp_ms,
                target_timestamp_ms=target_ms,
                settled_timestamp_ms=state.timestamp_ms,
                horizon_seconds=forecast.horizon_seconds,
                direction=forecast.direction,
                entry_spread=anchor.entry_spread,
                settled_spread=float(state.spread),
                predicted_signed_move_bps=forecast.expected_relative_move_bps,
                realized_signed_move_bps=realized_signed,
                realized_directional_gross_bps=directional_gross,
                expected_cost_bps=forecast.expected_cost_bps,
                realized_directional_net_bps=directional_net,
                forecast_error_bps=error,
                abstain=forecast.abstain,
                authority=RELATIVE_VALUE_AUTHORITY,
                execution_eligible=False,
            )
            self._settled.add(forecast_id)
            out.append(settled)
        return out