"""Same-world paired scoring for Phase 12 historical causal prosecution."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any

from .contracts import RELATIVE_VALUE_AUTHORITY
from .historical_causal_prosecution import (
    HistoricalWorldOutcome,
)


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class HistoricalPairedWorldDelta:
    schema: str
    pair_id: str

    mask_id: str

    world_state_id: str
    world_state_hash: str
    symbol: str
    timestamp_ms: int
    horizon_seconds: int

    decision_changed: bool
    direction_changed: bool
    abstention_changed: bool
    selection_changed: bool

    full_direction: str
    masked_direction: str

    full_abstain: bool
    masked_abstain: bool

    full_selected: bool | None
    masked_selected: bool | None

    full_net_bps: float | None
    masked_net_bps: float | None
    paired_delta_bps: float | None

    outcome_comparable: bool

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if not str(self.world_state_hash).startswith(
            "sha256:"
        ):
            raise ValueError(
                "historical_pair_world_hash_invalid"
            )

        if self.execution_eligible:
            raise ValueError(
                "historical_pair_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "historical_pair_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_historical_pair(
    *,
    mask_id: str,
    full: HistoricalWorldOutcome,
    masked: HistoricalWorldOutcome,
) -> HistoricalPairedWorldDelta:
    """Compare FULL_HIVE vs one mask on exactly the same historical world."""

    if (
        full.world_state_id
        != masked.world_state_id
    ):
        raise ValueError(
            "historical_pair_requires_same_world_id"
        )

    if (
        full.world_state_hash
        != masked.world_state_hash
    ):
        raise ValueError(
            "historical_pair_requires_same_world_hash"
        )

    if full.symbol != masked.symbol:
        raise ValueError(
            "historical_pair_requires_same_symbol"
        )

    if (
        full.timestamp_ms
        != masked.timestamp_ms
    ):
        raise ValueError(
            "historical_pair_requires_same_timestamp"
        )

    if (
        full.horizon_seconds
        != masked.horizon_seconds
    ):
        raise ValueError(
            "historical_pair_requires_same_horizon"
        )

    full_direction = str(
        full.direction
    ).upper()

    masked_direction = str(
        masked.direction
    ).upper()

    direction_changed = (
        full_direction
        != masked_direction
    )

    abstention_changed = (
        bool(full.abstain)
        != bool(masked.abstain)
    )

    selection_changed = (
        full.selected
        != masked.selected
    )

    decision_changed = bool(
        direction_changed
        or abstention_changed
        or selection_changed
    )

    full_net = (
        None
        if full.realized_net_bps is None
        else float(full.realized_net_bps)
    )

    masked_net = (
        None
        if masked.realized_net_bps is None
        else float(masked.realized_net_bps)
    )

    comparable = bool(
        full_net is not None
        and masked_net is not None
        and math.isfinite(full_net)
        and math.isfinite(masked_net)
    )

    paired_delta = (
        full_net - masked_net
        if comparable
        else None
    )

    body = {
        "mask_id": str(mask_id),
        "world_state_id":
            full.world_state_id,
        "world_state_hash":
            full.world_state_hash,
        "symbol": full.symbol,
        "timestamp_ms":
            full.timestamp_ms,
        "horizon_seconds":
            full.horizon_seconds,
        "full_direction":
            full_direction,
        "masked_direction":
            masked_direction,
        "full_abstain":
            bool(full.abstain),
        "masked_abstain":
            bool(masked.abstain),
        "full_selected":
            full.selected,
        "masked_selected":
            masked.selected,
        "full_net_bps":
            full_net,
        "masked_net_bps":
            masked_net,
    }

    return HistoricalPairedWorldDelta(
        schema=(
            "hivenance_historical_paired_world_delta_v1"
        ),
        pair_id=(
            "hpwd_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        mask_id=str(mask_id),
        world_state_id=(
            full.world_state_id
        ),
        world_state_hash=(
            full.world_state_hash
        ),
        symbol=full.symbol,
        timestamp_ms=int(
            full.timestamp_ms
        ),
        horizon_seconds=int(
            full.horizon_seconds
        ),
        decision_changed=(
            decision_changed
        ),
        direction_changed=(
            direction_changed
        ),
        abstention_changed=(
            abstention_changed
        ),
        selection_changed=(
            selection_changed
        ),
        full_direction=(
            full_direction
        ),
        masked_direction=(
            masked_direction
        ),
        full_abstain=bool(
            full.abstain
        ),
        masked_abstain=bool(
            masked.abstain
        ),
        full_selected=(
            full.selected
        ),
        masked_selected=(
            masked.selected
        ),
        full_net_bps=full_net,
        masked_net_bps=masked_net,
        paired_delta_bps=(
            None
            if paired_delta is None
            else round(
                paired_delta,
                9,
            )
        ),
        outcome_comparable=(
            comparable
        ),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
