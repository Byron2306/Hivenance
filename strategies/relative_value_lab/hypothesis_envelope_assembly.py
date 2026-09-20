"""Assemble the Phase 1-10 organism into one canonical Hypothesis Envelope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import (
    ForwardRelativeForecast,
)
from .hypothesis_envelope import (
    CanonicalHypothesisEnvelope,
    HypothesisConclusion,
    build_hypothesis_envelope,
)


@dataclass(frozen=True)
class FullOrganismEnvelopeInputs:
    canonical_score_frame: Any
    world_state_page: Any
    temporal_lattice: Any
    evidence_bees: Any
    comparison_packet: Any
    selection_state: Any
    regime: Any
    worker_proposals: Any
    phoenix_hypotheses: Any
    crystal_learning_context: Any
    quorum: Any
    pollen_state: Any
    triune_scores: Any
    queen_receipt: Any
    queen_epoch: Any
    recursive_research: Any
    controls: Any

    def sections(self) -> dict[str, Any]:
        return {
            "canonical_score_frame":
                self.canonical_score_frame,
            "world_state_page":
                self.world_state_page,
            "temporal_lattice":
                self.temporal_lattice,
            "evidence_bees":
                self.evidence_bees,
            "comparison_packet":
                self.comparison_packet,
            "selection_state":
                self.selection_state,
            "regime":
                self.regime,
            "worker_proposals":
                self.worker_proposals,
            "phoenix_hypotheses":
                self.phoenix_hypotheses,
            "crystal_learning_context":
                self.crystal_learning_context,
            "quorum":
                self.quorum,
            "pollen_state":
                self.pollen_state,
            "triune_scores":
                self.triune_scores,
            "queen_receipt":
                self.queen_receipt,
            "queen_epoch":
                self.queen_epoch,
            "recursive_research":
                self.recursive_research,
            "controls":
                self.controls,
        }


def _to_mapping(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _to_mapping(
            value.to_dict()
        )

    if isinstance(value, Mapping):
        return {
            str(k): _to_mapping(v)
            for k, v in value.items()
        }

    if isinstance(value, (tuple, list)):
        return tuple(
            _to_mapping(v)
            for v in value
        )

    if isinstance(value, set):
        return tuple(
            _to_mapping(v)
            for v in value
        )

    return value


def _walk(
    value: Any,
    *,
    path: str,
):
    yield path, value

    mapped = _to_mapping(value)

    if isinstance(mapped, Mapping):
        for key, child in mapped.items():
            yield from _walk(
                child,
                path=(
                    f"{path}.{key}"
                    if path
                    else str(key)
                ),
            )

    elif isinstance(
        mapped,
        (tuple, list),
    ):
        for index, child in enumerate(
            mapped
        ):
            yield from _walk(
                child,
                path=f"{path}[{index}]",
            )


def validate_envelope_inputs(
    *,
    inputs: FullOrganismEnvelopeInputs,
    world_state_id: str,
    world_state_hash: str,
) -> None:
    """Reject cross-world or authority-escalating material anywhere inside."""

    for section_name, section in (
        inputs.sections().items()
    ):
        for path, value in _walk(
            section,
            path=section_name,
        ):
            if not isinstance(
                value,
                Mapping,
            ):
                value = _to_mapping(value)

            if not isinstance(
                value,
                Mapping,
            ):
                continue

            declared_world_id = (
                value.get(
                    "world_state_id"
                )
            )

            declared_world_hash = (
                value.get(
                    "world_state_hash"
                )
            )

            if (
                declared_world_id
                is not None
                and str(declared_world_id)
                != str(world_state_id)
            ):
                raise ValueError(
                    "hypothesis_envelope_cross_world_id:"
                    + path
                )

            if (
                declared_world_hash
                is not None
                and str(declared_world_hash)
                != str(world_state_hash)
            ):
                raise ValueError(
                    "hypothesis_envelope_cross_world_hash:"
                    + path
                )

            if (
                value.get(
                    "execution_eligible"
                )
                is True
            ):
                raise ValueError(
                    "hypothesis_envelope_execution_authority_found:"
                    + path
                )

            if (
                value.get(
                    "promotion_eligible"
                )
                is True
            ):
                raise ValueError(
                    "hypothesis_envelope_promotion_authority_found:"
                    + path
                )


def conclusion_from_forecast(
    *,
    hypothesis_id: str,
    forecast: ForwardRelativeForecast,
    influence_ids: Sequence[str],
) -> HypothesisConclusion:
    """Freeze the already-produced forecast conclusion, never recompute it."""

    direction = str(
        forecast.direction
    ).upper()

    abstain = bool(
        forecast.abstain
    )

    if abstain:
        direction = "ABSTAIN"

    return HypothesisConclusion(
        hypothesis_id=str(
            hypothesis_id
        ),
        forecast_id=str(
            forecast.forecast_id
        ),
        symbol=str(
            forecast.pair_id
        ),
        timestamp_ms=int(
            forecast.timestamp_ms
        ),
        horizon_seconds=int(
            forecast.horizon_seconds
        ),
        direction=direction,
        abstain=abstain,
        expected_move_bps=(
            forecast.expected_relative_move_bps
        ),
        expected_cost_bps=(
            forecast.expected_cost_bps
        ),
        expected_net_bps=(
            forecast.expected_net_bps
        ),
        uncertainty=(
            forecast.uncertainty
        ),
        influence_ids=tuple(
            sorted(
                set(
                    map(
                        str,
                        influence_ids,
                    )
                )
            )
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )


def assemble_full_organism_envelope(
    *,
    hypothesis_id: str,
    forecast: ForwardRelativeForecast,
    inputs: FullOrganismEnvelopeInputs,
    world_state_id: str,
    world_state_hash: str,
    frozen_at_ms: int,
    influence_ids: Sequence[str],
) -> CanonicalHypothesisEnvelope:

    validate_envelope_inputs(
        inputs=inputs,
        world_state_id=world_state_id,
        world_state_hash=world_state_hash,
    )

    conclusion = conclusion_from_forecast(
        hypothesis_id=hypothesis_id,
        forecast=forecast,
        influence_ids=influence_ids,
    )

    return build_hypothesis_envelope(
        hypothesis_id=hypothesis_id,
        forecast_id=forecast.forecast_id,
        world_state_id=world_state_id,
        world_state_hash=world_state_hash,
        frozen_at_ms=frozen_at_ms,
        sections=inputs.sections(),
        declared_influence_ids=(
            influence_ids
        ),
        conclusion=conclusion,
    )
