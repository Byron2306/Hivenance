"""Veto-aware historical outcome scoring for reconstructed Phoenix forecasts.

This is intentionally separate from historical_envelope_outcome.py.

The envelope scorer uses None for abstentions because an abstaining forecast has
no directional realized return.

For causal veto prosecution we need the economic counterfactual:

    trade -> realized directional net return
    abstain/no-trade -> 0.0 bps

That permits a lawful comparison of a challenged FULL path against an organ-
blind directional forecast on the exact same immutable future settlement tape.
"""

from __future__ import annotations

from typing import Any

from strategies.volatility_breakout.models import Forecast

from .historical_envelope_outcome import (
    HistoricalWorldOutcome,
)
from .historical_real_settlement_tape import (
    HistoricalRealSettlementTruth,
)


def forecast_outcome_on_real_tape(
    *,
    forecast: Forecast,
    truth: HistoricalRealSettlementTruth,
    world_state_id: str,
    world_state_hash: str,
) -> HistoricalWorldOutcome:
    if (
        int(forecast.timestamp_ms)
        != int(truth.forecast_timestamp_ms)
    ):
        raise ValueError(
            "historical_forecast_tape_timestamp_mismatch"
        )

    if (
        int(forecast.horizon_seconds)
        != int(truth.horizon_seconds)
    ):
        raise ValueError(
            "historical_forecast_tape_horizon_mismatch"
        )

    if (
        str(forecast.symbol)
        != str(truth.symbol)
    ):
        raise ValueError(
            "historical_forecast_tape_symbol_mismatch"
        )

    direction = str(
        forecast.direction
    ).upper()

    abstain = bool(
        forecast.abstain
        or direction == "ABSTAIN"
    )

    if abstain:
        realized_net = 0.0

    else:
        if direction == "UP":
            sign = 1.0
        elif direction == "DOWN":
            sign = -1.0
        else:
            raise ValueError(
                "historical_forecast_direction_invalid:"
                + direction
            )

        gross = (
            sign
            * float(
                truth.realized_signed_move_bps
            )
        )

        cost = (
            forecast.expected_cost_bps
        )

        if cost is None:
            cost = (
                truth.realized_roundtrip_cost_bps
            )

        realized_net = (
            gross
            - float(cost)
        )

    return HistoricalWorldOutcome(
        world_state_id=str(
            world_state_id
        ),
        world_state_hash=str(
            world_state_hash
        ),
        symbol=str(
            truth.symbol
        ),
        timestamp_ms=int(
            truth.forecast_timestamp_ms
        ),
        horizon_seconds=int(
            truth.horizon_seconds
        ),
        direction=direction,
        abstain=abstain,
        selected=None,
        realized_net_bps=float(
            realized_net
        ),
        envelope_id=None,
        execution_eligible=False,
        promotion_eligible=False,
    )
