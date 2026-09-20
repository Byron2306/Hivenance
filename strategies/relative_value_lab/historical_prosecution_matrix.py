"""Phase-12 complete historical causal prosecution matrix.

One frozen historical case is replayed through the entire canonical mask roster.
Every mask must produce a fresh HypothesisEnvelope from the same observed world.
All outcomes are scored against one immutable settlement tape.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from .contracts import RELATIVE_VALUE_AUTHORITY
from .historical_causal_prosecution import (
    PAIRED_MASKS,
    HistoricalOrganProsecution,
)
from .historical_envelope_outcome import (
    HistoricalSettlementTape,
    outcome_from_envelope,
)
from .historical_mask_engine import (
    HistoricalMaskPlan,
    historical_mask_plan,
)
from .historical_paired_world import (
    HistoricalPairedWorldDelta,
    score_historical_pair,
)
from .hypothesis_envelope import (
    CanonicalHypothesisEnvelope,
)


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return "sha256:" + hashlib.sha256(
        raw
    ).hexdigest()


@dataclass(frozen=True)
class HistoricalMatrixCase:
    case_id: str
    full_envelope: CanonicalHypothesisEnvelope
    settlement_tape: HistoricalSettlementTape
    dependence_cluster_id: str

    execution_eligible: bool = False
    promotion_eligible: bool = False


@dataclass(frozen=True)
class HistoricalMaskReplay:
    mask_id: str
    envelope: CanonicalHypothesisEnvelope

    execution_eligible: bool = False
    promotion_eligible: bool = False


@dataclass(frozen=True)
class HistoricalMatrixCaseResult:
    schema: str
    result_id: str

    case_id: str
    world_state_id: str
    world_state_hash: str

    full_envelope_id: str

    mask_replays: tuple[
        HistoricalMaskReplay,
        ...
    ]

    paired_deltas: tuple[
        HistoricalPairedWorldDelta,
        ...
    ]

    dependence_cluster_id: str

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ReplayMaskFn = Callable[
    [
        HistoricalMaskPlan,
        HistoricalMatrixCase,
    ],
    CanonicalHypothesisEnvelope,
]


def run_historical_matrix_case(
    *,
    case: HistoricalMatrixCase,
    replay_mask: ReplayMaskFn,
) -> HistoricalMatrixCaseResult:
    full = case.full_envelope

    full_outcome = outcome_from_envelope(
        envelope=full,
        tape=case.settlement_tape,
    )

    replays = []
    deltas = []

    envelope_ids = set()

    for mask_id in PAIRED_MASKS:
        plan = historical_mask_plan(
            mask_id
        )

        if mask_id == "FULL_HIVE":
            replayed = full
        else:
            replayed = replay_mask(
                plan,
                case,
            )

        if not isinstance(
            replayed,
            CanonicalHypothesisEnvelope,
        ):
            raise TypeError(
                "historical_matrix_replay_must_return_envelope"
            )

        if (
            replayed.world_state_id
            != full.world_state_id
        ):
            raise ValueError(
                "historical_matrix_cross_world_id:"
                + mask_id
            )

        if (
            replayed.world_state_hash
            != full.world_state_hash
        ):
            raise ValueError(
                "historical_matrix_cross_world_hash:"
                + mask_id
            )

        if (
            replayed.conclusion.symbol
            != full.conclusion.symbol
        ):
            raise ValueError(
                "historical_matrix_symbol_mismatch:"
                + mask_id
            )

        if (
            replayed.conclusion.timestamp_ms
            != full.conclusion.timestamp_ms
        ):
            raise ValueError(
                "historical_matrix_timestamp_mismatch:"
                + mask_id
            )

        if (
            replayed.conclusion.horizon_seconds
            != full.conclusion.horizon_seconds
        ):
            raise ValueError(
                "historical_matrix_horizon_mismatch:"
                + mask_id
            )

        # FULL_HIVE deliberately reuses the original frozen envelope.
        # Every actual counterfactual must be freshly produced.
        if (
            mask_id != "FULL_HIVE"
            and replayed.envelope_id
            == full.envelope_id
        ):
            raise ValueError(
                "historical_matrix_mask_did_not_produce_fresh_envelope:"
                + mask_id
            )

        if replayed.envelope_id in envelope_ids:
            raise ValueError(
                "historical_matrix_duplicate_mask_envelope:"
                + mask_id
            )

        envelope_ids.add(
            replayed.envelope_id
        )

        replays.append(
            HistoricalMaskReplay(
                mask_id=mask_id,
                envelope=replayed,
                execution_eligible=False,
                promotion_eligible=False,
            )
        )

        if mask_id == "FULL_HIVE":
            continue

        masked_outcome = (
            outcome_from_envelope(
                envelope=replayed,
                tape=(
                    case.settlement_tape
                ),
            )
        )

        deltas.append(
            score_historical_pair(
                mask_id=mask_id,
                full=full_outcome,
                masked=masked_outcome,
            )
        )

    if len(replays) != len(
        PAIRED_MASKS
    ):
        raise AssertionError(
            "historical_matrix_incomplete_mask_roster"
        )

    body = {
        "case_id": case.case_id,
        "world_state_id":
            full.world_state_id,
        "world_state_hash":
            full.world_state_hash,
        "full_envelope_id":
            full.envelope_id,
        "mask_envelope_ids": {
            row.mask_id:
                row.envelope.envelope_id
            for row in replays
        },
        "pair_ids": [
            row.pair_id
            for row in deltas
        ],
        "dependence_cluster_id":
            case.dependence_cluster_id,
    }

    return HistoricalMatrixCaseResult(
        schema=(
            "hivenance_historical_prosecution_matrix_case_v1"
        ),
        result_id=(
            "hmat_"
            + _digest(body).split(
                ":",
                1,
            )[1][:24]
        ),
        case_id=case.case_id,
        world_state_id=(
            full.world_state_id
        ),
        world_state_hash=(
            full.world_state_hash
        ),
        full_envelope_id=(
            full.envelope_id
        ),
        mask_replays=tuple(
            replays
        ),
        paired_deltas=tuple(
            deltas
        ),
        dependence_cluster_id=(
            case.dependence_cluster_id
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )
