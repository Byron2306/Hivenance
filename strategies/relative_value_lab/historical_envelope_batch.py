"""Batch historical prosecution over stored FULL_HIVE/masked envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .historical_causal_prosecution import (
    HistoricalOrganProsecution,
)
from .historical_envelope_outcome import (
    HistoricalSettlementTape,
    outcome_from_envelope,
)
from .historical_pair_aggregation import (
    aggregate_historical_pairs,
)
from .historical_paired_world import (
    HistoricalPairedWorldDelta,
    score_historical_pair,
)
from .hypothesis_envelope_store import (
    load_persisted_envelope,
)


@dataclass(frozen=True)
class HistoricalEnvelopePairInput:
    full_envelope_path: Path
    masked_envelope_path: Path
    settlement_tape: HistoricalSettlementTape
    dependence_cluster_id: str


@dataclass(frozen=True)
class HistoricalEnvelopeBatchResult:
    organ_id: str
    mask_id: str
    pairs: tuple[
        HistoricalPairedWorldDelta,
        ...
    ]
    prosecution: HistoricalOrganProsecution

    execution_eligible: bool = False
    promotion_eligible: bool = False


def prosecute_envelope_batch(
    *,
    organ_id: str,
    mask_id: str,
    cases: Sequence[
        HistoricalEnvelopePairInput
    ],
    available: bool,
    invoked_count: int,
    non_default_output_count: int,
    minimum_paired_worlds: int = 5,
) -> HistoricalEnvelopeBatchResult:

    paired = []
    clusters = []

    seen = set()

    for case in cases:
        full = load_persisted_envelope(
            case.full_envelope_path
        )

        masked = load_persisted_envelope(
            case.masked_envelope_path
        )

        identity = (
            full.world_state_id,
            full.world_state_hash,
            full.conclusion.symbol,
            full.conclusion.timestamp_ms,
            full.conclusion.horizon_seconds,
            str(mask_id),
        )

        if identity in seen:
            raise ValueError(
                "duplicate_historical_envelope_pair"
            )

        seen.add(identity)

        full_outcome = outcome_from_envelope(
            envelope=full,
            tape=case.settlement_tape,
        )

        masked_outcome = outcome_from_envelope(
            envelope=masked,
            tape=case.settlement_tape,
        )

        pair = score_historical_pair(
            mask_id=mask_id,
            full=full_outcome,
            masked=masked_outcome,
        )

        paired.append(pair)

        clusters.append(
            str(
                case.dependence_cluster_id
            )
        )

    prosecution = aggregate_historical_pairs(
        organ_id=organ_id,
        mask_id=mask_id,
        available=available,
        invoked_count=invoked_count,
        non_default_output_count=(
            non_default_output_count
        ),
        pairs=tuple(paired),
        minimum_paired_worlds=(
            minimum_paired_worlds
        ),
        dependence_cluster_ids=(
            tuple(clusters)
        ),
    )

    return HistoricalEnvelopeBatchResult(
        organ_id=str(organ_id),
        mask_id=str(mask_id),
        pairs=tuple(paired),
        prosecution=prosecution,
        execution_eligible=False,
        promotion_eligible=False,
    )
