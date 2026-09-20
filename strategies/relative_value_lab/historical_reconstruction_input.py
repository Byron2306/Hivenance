"""Phase-12 historical reconstruction input boundary.

Builds one immutable pre-decision input package from the real Phase-4 corpus.

Absolutely no settlement/future information may cross this boundary.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .historical_real_corpus import HistoricalCorpusCase


FUTURE_FORBIDDEN_KEYS = {
    "exit_price",
    "exit_custody_ts",
    "settled_ts",
    "settlement_id",
    "gross_absolute_move_bps",
    "net_opportunity_bps",
    "profitable_opportunity",
    "realized_roundtrip_cost_bps",
    "realized_signed_move_bps",
    "directional_return_bps",
    "gross_return_bps",
    "net_return_bps",
    "positive_net",
    "outcome",
    "outcome_class",
}


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return (
        "sha256:"
        + hashlib.sha256(raw).hexdigest()
    )


def _find_forbidden(
    value: Any,
    *,
    path: str = "$",
) -> tuple[str, ...]:
    found: list[str] = []

    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key)

            if name.lower() in FUTURE_FORBIDDEN_KEYS:
                found.append(
                    path + "." + name
                )

            found.extend(
                _find_forbidden(
                    child,
                    path=path + "." + name,
                )
            )

    elif isinstance(value, (tuple, list)):
        for i, child in enumerate(value):
            found.extend(
                _find_forbidden(
                    child,
                    path=f"{path}[{i}]",
                )
            )

    return tuple(found)


@dataclass(frozen=True)
class HistoricalReconstructionInput:
    schema: str
    reconstruction_id: str

    case_id: str
    freeze_id: str
    observation_run_id: str

    symbol: str
    horizon_seconds: int

    observed_at_ms: int
    target_at_ms: int

    world_state_id: str
    world_state_hash: str
    evidence_root: str

    observation_source: str

    observation: Mapping[str, Any]
    selector_state: Mapping[str, Any]
    regime_state: Mapping[str, Any]
    cost_state: Mapping[str, Any]

    # No later Phase-2 forecast context existed for this cohort.
    historical_hypothesis_context_available: bool
    historical_outcome_context_available: bool

    retrospective_reconstruction_only: bool = True

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        forbidden = _find_forbidden(
            {
                "observation": self.observation,
                "selector_state": self.selector_state,
                "regime_state": self.regime_state,
                "cost_state": self.cost_state,
            }
        )

        if forbidden:
            raise ValueError(
                "historical_reconstruction_future_leak:"
                + ",".join(forbidden)
            )

        if (
            self.target_at_ms
            <= self.observed_at_ms
        ):
            raise ValueError(
                "historical_reconstruction_target_not_future"
            )

        if (
            self.target_at_ms
            - self.observed_at_ms
            != self.horizon_seconds * 1000
        ):
            raise ValueError(
                "historical_reconstruction_horizon_mismatch"
            )

        if not self.retrospective_reconstruction_only:
            raise ValueError(
                "historical_reconstruction_must_be_retrospective"
            )

        if self.execution_eligible:
            raise ValueError(
                "historical_reconstruction_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "historical_reconstruction_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reconstruction_input_from_case(
    case: HistoricalCorpusCase,
) -> HistoricalReconstructionInput:
    if case.observation_snapshot is None:
        raise ValueError(
            "historical_reconstruction_observation_missing:"
            + case.freeze_id
        )

    observation = dict(
        case.observation_snapshot
    )

    source = str(
        observation.pop(
            "_historical_source_table",
            "UNKNOWN",
        )
    )

    # Remove storage-only metadata that is not an organism feature.
    observation.pop(
        "id",
        None,
    )

    freeze = dict(
        case.freeze_payload
    )

    observed_ms = freeze.get(
        "observed_at_ms"
    )

    if observed_ms is None:
        observed_ms = round(
            case.observed_ts
            * 1000.0
        )

    observed_ms = int(
        observed_ms
    )

    target_ms = int(
        round(
            case.target_ts
            * 1000.0
        )
    )

    selector_state = {
        "freeze_id":
            case.freeze_id,
        "selector_rank":
            case.selector_rank,
        "selector_score":
            freeze.get(
                "selector_score"
            ),
        "selected":
            case.selected,
        "blind_rank":
            case.blind_rank,
        "blind_selected":
            case.blind_selected,
    }

    regime_state = {
        "regime":
            case.regime,
    }

    cost_state = {
        # This is the cost estimate available at freeze time,
        # NOT realized future cost.
        "predicted_roundtrip_cost_bps":
            case.predicted_roundtrip_cost_bps,
    }

    body = {
        "case_id":
            case.case_id,
        "freeze_id":
            case.freeze_id,
        "run_id":
            case.observation_run_id,
        "symbol":
            case.symbol,
        "horizon":
            case.horizon_seconds,
        "observed_at_ms":
            observed_ms,
        "target_at_ms":
            target_ms,
        "world_state_id":
            case.world_state_id,
        "world_state_hash":
            case.world_state_hash,
        "evidence_root":
            case.evidence_root,
        "observation_source":
            source,
        "observation":
            observation,
        "selector_state":
            selector_state,
        "regime_state":
            regime_state,
        "cost_state":
            cost_state,
    }

    return HistoricalReconstructionInput(
        schema=(
            "hivenance_historical_reconstruction_input_v1"
        ),
        reconstruction_id=(
            "hrecon_"
            + _digest(body).split(
                ":",
                1,
            )[1][:24]
        ),
        case_id=case.case_id,
        freeze_id=case.freeze_id,
        observation_run_id=(
            case.observation_run_id
        ),
        symbol=case.symbol,
        horizon_seconds=(
            case.horizon_seconds
        ),
        observed_at_ms=(
            observed_ms
        ),
        target_at_ms=(
            target_ms
        ),
        world_state_id=(
            case.world_state_id
        ),
        world_state_hash=(
            case.world_state_hash
        ),
        evidence_root=(
            case.evidence_root
        ),
        observation_source=(
            source
        ),
        observation=observation,
        selector_state=(
            selector_state
        ),
        regime_state=(
            regime_state
        ),
        cost_state=(
            cost_state
        ),
        historical_hypothesis_context_available=bool(
            case.matching_forecasts
        ),
        historical_outcome_context_available=bool(
            case.matching_outcomes
        ),
        retrospective_reconstruction_only=True,
        execution_eligible=False,
        promotion_eligible=False,
    )
