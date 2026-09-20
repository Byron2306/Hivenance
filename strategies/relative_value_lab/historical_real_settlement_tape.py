"""Real future settlement tape for Phase-12 historical reconstruction.

The Phase-4 selector cohort did not freeze directional forecasts. Therefore:

* future market movement is reconstructed only from frozen entry/exit prices;
* direction is NOT inferred as a historical prediction;
* realized transaction cost comes from the frozen settlement;
* model direction must come from a separately labelled historical reconstruction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .historical_envelope_outcome import (
    HistoricalSettlementTape,
)
from .historical_real_corpus import (
    HistoricalCorpusCase,
)


@dataclass(frozen=True)
class HistoricalRealSettlementTruth:
    case_id: str
    freeze_id: str
    settlement_id: str

    symbol: str

    forecast_timestamp_ms: int
    target_timestamp_ms: int
    settled_timestamp_ms: int

    horizon_seconds: int

    entry_price: float
    exit_price: float

    realized_signed_move_bps: float
    recorded_gross_absolute_move_bps: float | None
    absolute_move_error_bps: float | None

    realized_roundtrip_cost_bps: float
    recorded_net_opportunity_bps: float | None

    historical_direction_frozen: bool = False
    retrospective_reconstruction_only: bool = True

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_settlement_tape(
        self,
    ) -> HistoricalSettlementTape:
        return HistoricalSettlementTape(
            forecast_timestamp_ms=(
                self.forecast_timestamp_ms
            ),
            horizon_seconds=(
                self.horizon_seconds
            ),
            settled_timestamp_ms=(
                self.settled_timestamp_ms
            ),
            realized_signed_move_bps=(
                self.realized_signed_move_bps
            ),
            expected_cost_bps=(
                self.realized_roundtrip_cost_bps
            ),
            source_forecast_id=(
                "historical-reconstruction:"
                + self.freeze_id
            ),
        )


def real_settlement_truth(
    case: HistoricalCorpusCase,
) -> HistoricalRealSettlementTruth:
    settlement = dict(
        case.settlement_payload
    )

    entry = float(
        case.entry_price
    )
    exit_price = float(
        case.exit_price
    )

    if entry <= 0.0:
        raise ValueError(
            "historical_real_entry_price_invalid"
        )

    signed_move = (
        (exit_price / entry) - 1.0
    ) * 10_000.0

    recorded_abs = (
        case.gross_absolute_move_bps
    )

    abs_error = (
        None
        if recorded_abs is None
        else abs(
            abs(signed_move)
            - float(recorded_abs)
        )
    )

    # The original settlement explicitly froze realized round-trip cost.
    cost = settlement.get(
        "realized_roundtrip_cost_bps"
    )

    if cost is None:
        raise ValueError(
            "historical_realized_cost_missing:"
            + case.freeze_id
        )

    cost = float(cost)

    if cost < 0.0:
        raise ValueError(
            "historical_realized_cost_negative:"
            + case.freeze_id
        )

    observed_ms = case.freeze_payload.get(
        "observed_at_ms"
    )

    if observed_ms is None:
        observed_ms = round(
            case.observed_ts
            * 1000.0
        )

    target_ms = round(
        case.target_ts
        * 1000.0
    )

    settled_ms = round(
        case.settled_ts
        * 1000.0
    )

    return HistoricalRealSettlementTruth(
        case_id=case.case_id,
        freeze_id=case.freeze_id,
        settlement_id=(
            case.settlement_id
        ),
        symbol=case.symbol,
        forecast_timestamp_ms=int(
            observed_ms
        ),
        target_timestamp_ms=int(
            target_ms
        ),
        settled_timestamp_ms=int(
            settled_ms
        ),
        horizon_seconds=(
            case.horizon_seconds
        ),
        entry_price=entry,
        exit_price=exit_price,
        realized_signed_move_bps=(
            float(signed_move)
        ),
        recorded_gross_absolute_move_bps=(
            None
            if recorded_abs is None
            else float(recorded_abs)
        ),
        absolute_move_error_bps=(
            abs_error
        ),
        realized_roundtrip_cost_bps=(
            cost
        ),
        recorded_net_opportunity_bps=(
            case.net_opportunity_bps
        ),
        historical_direction_frozen=False,
        retrospective_reconstruction_only=True,
        execution_eligible=False,
        promotion_eligible=False,
    )
