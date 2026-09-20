"""Convert frozen hypothesis envelopes into Phase-12 historical outcomes.

All variants are scored against the same already-observed future settlement
tape. No model refitting or future-data reinterpretation occurs here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .hypothesis_envelope import (
    CanonicalHypothesisEnvelope,
)
from .historical_causal_prosecution import (
    HistoricalWorldOutcome,
)
from .settlement import (
    SettledRelativeForecast,
)


@dataclass(frozen=True)
class HistoricalSettlementTape:
    forecast_timestamp_ms: int
    horizon_seconds: int
    settled_timestamp_ms: int

    realized_signed_move_bps: float
    expected_cost_bps: float | None

    source_forecast_id: str

    execution_eligible: bool = False
    promotion_eligible: bool = False

    @classmethod
    def from_settlement(
        cls,
        settlement: SettledRelativeForecast,
    ) -> "HistoricalSettlementTape":
        return cls(
            forecast_timestamp_ms=int(
                settlement.forecast_timestamp_ms
            ),
            horizon_seconds=int(
                settlement.horizon_seconds
            ),
            settled_timestamp_ms=int(
                settlement.settled_timestamp_ms
            ),
            realized_signed_move_bps=float(
                settlement.realized_signed_move_bps
            ),
            expected_cost_bps=(
                None
                if settlement.expected_cost_bps
                is None
                else float(
                    settlement.expected_cost_bps
                )
            ),
            source_forecast_id=str(
                settlement.forecast_id
            ),
            execution_eligible=False,
            promotion_eligible=False,
        )


def _direction_sign(
    direction: str,
) -> float | None:
    direction = str(
        direction
    ).upper()

    if direction in {
        "UP",
        "LONG",
        "LONG_A_SHORT_B",
    }:
        return 1.0

    if direction in {
        "DOWN",
        "SHORT",
        "LONG_B_SHORT_A",
    }:
        return -1.0

    if direction == "ABSTAIN":
        return None

    raise ValueError(
        "historical_envelope_unknown_direction:"
        + direction
    )


def _selection_from_envelope(
    envelope: CanonicalHypothesisEnvelope,
) -> bool | None:
    section = envelope.sections.get(
        "selection_state"
    )

    if not isinstance(
        section,
        Mapping,
    ):
        return None

    if isinstance(
        section.get("selected"),
        bool,
    ):
        return bool(
            section["selected"]
        )

    symbol = envelope.conclusion.symbol

    selected = section.get(
        "selected"
    )

    if isinstance(
        selected,
        (tuple, list, set),
    ):
        return symbol in {
            str(x)
            for x in selected
        }

    rejected = section.get(
        "rejected"
    )

    if isinstance(
        rejected,
        (tuple, list, set),
    ) and symbol in {
        str(x)
        for x in rejected
    }:
        return False

    return None


def outcome_from_envelope(
    *,
    envelope: CanonicalHypothesisEnvelope,
    tape: HistoricalSettlementTape,
) -> HistoricalWorldOutcome:
    """Score one frozen conclusion on one immutable future tape."""

    conclusion = envelope.conclusion

    if (
        int(conclusion.timestamp_ms)
        != int(
            tape.forecast_timestamp_ms
        )
    ):
        raise ValueError(
            "historical_envelope_tape_timestamp_mismatch"
        )

    if (
        int(conclusion.horizon_seconds)
        != int(
            tape.horizon_seconds
        )
    ):
        raise ValueError(
            "historical_envelope_tape_horizon_mismatch"
        )

    direction = str(
        conclusion.direction
    ).upper()

    abstain = bool(
        conclusion.abstain
        or direction == "ABSTAIN"
    )

    sign = _direction_sign(
        direction
    )

    realized_net = None

    if (
        not abstain
        and sign is not None
    ):
        gross = (
            sign
            * float(
                tape.realized_signed_move_bps
            )
        )

        cost = (
            conclusion.expected_cost_bps
        )

        if cost is None:
            cost = tape.expected_cost_bps

        if cost is not None:
            realized_net = (
                gross
                - float(cost)
            )

    return HistoricalWorldOutcome(
        world_state_id=(
            envelope.world_state_id
        ),
        world_state_hash=(
            envelope.world_state_hash
        ),
        symbol=str(
            conclusion.symbol
        ),
        timestamp_ms=int(
            conclusion.timestamp_ms
        ),
        horizon_seconds=int(
            conclusion.horizon_seconds
        ),
        direction=direction,
        abstain=abstain,
        selected=(
            _selection_from_envelope(
                envelope
            )
        ),
        realized_net_bps=(
            realized_net
        ),
        envelope_id=(
            envelope.envelope_id
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )
