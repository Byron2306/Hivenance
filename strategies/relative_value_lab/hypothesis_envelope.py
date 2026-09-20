"""Canonical immutable research envelope for the full HiveNance organism.

The envelope does not create cognition or authority. It freezes the exact
research state that already existed at decision time and makes undeclared
influence detectable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


SCHEMA = "hivenance_canonical_hypothesis_envelope_v1"


REQUIRED_SECTIONS = (
    "canonical_score_frame",
    "world_state_page",
    "temporal_lattice",
    "evidence_bees",
    "comparison_packet",
    "selection_state",
    "regime",
    "worker_proposals",
    "phoenix_hypotheses",
    "crystal_learning_context",
    "quorum",
    "pollen_state",
    "triune_scores",
    "queen_receipt",
    "queen_epoch",
    "recursive_research",
    "controls",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def canonical_digest(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            _canonical_json(value).encode("utf-8")
        ).hexdigest()
    )


@dataclass(frozen=True)
class HypothesisConclusion:
    hypothesis_id: str
    forecast_id: str
    symbol: str
    timestamp_ms: int
    horizon_seconds: int

    direction: str
    abstain: bool

    expected_move_bps: float | None
    expected_cost_bps: float | None
    expected_net_bps: float | None
    uncertainty: float | None

    influence_ids: tuple[str, ...]

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        direction = str(self.direction).upper()

        if self.abstain and direction != "ABSTAIN":
            raise ValueError(
                "abstaining_conclusion_requires_abstain_direction"
            )

        if not self.abstain and direction == "ABSTAIN":
            raise ValueError(
                "nonabstaining_conclusion_cannot_have_abstain_direction"
            )

        if self.execution_eligible:
            raise ValueError(
                "hypothesis_conclusion_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "hypothesis_conclusion_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalHypothesisEnvelope:
    schema: str
    envelope_id: str

    hypothesis_id: str
    forecast_id: str

    world_state_id: str
    world_state_hash: str

    frozen_at_ms: int

    section_digests: Mapping[str, str]
    sections: Mapping[str, Any]

    declared_influence_ids: tuple[str, ...]
    conclusion: HypothesisConclusion

    canonical_payload_digest: str

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise ValueError(
                "hypothesis_envelope_schema_mismatch"
            )

        if self.execution_eligible:
            raise ValueError(
                "hypothesis_envelope_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "hypothesis_envelope_promotion_forbidden"
            )

        if not str(self.world_state_hash).startswith(
            "sha256:"
        ):
            raise ValueError(
                "hypothesis_envelope_world_hash_invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "envelope_id": self.envelope_id,
            "hypothesis_id": self.hypothesis_id,
            "forecast_id": self.forecast_id,
            "world_state_id": self.world_state_id,
            "world_state_hash": self.world_state_hash,
            "frozen_at_ms": self.frozen_at_ms,
            "section_digests": dict(
                self.section_digests
            ),
            "sections": dict(self.sections),
            "declared_influence_ids":
                self.declared_influence_ids,
            "conclusion": self.conclusion.to_dict(),
            "canonical_payload_digest":
                self.canonical_payload_digest,
            "authority": self.authority,
            "execution_eligible": False,
            "promotion_eligible": False,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(
            self.to_dict()
        ).encode("utf-8")


def _freeze(value: Any) -> Any:
    """Convert dataclass / receipt-like objects to canonical JSON-safe shape."""

    if hasattr(value, "to_dict"):
        return _freeze(value.to_dict())

    if isinstance(value, Mapping):
        return {
            str(key): _freeze(value[key])
            for key in sorted(
                value,
                key=lambda x: str(x),
            )
        }

    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze(item)
            for item in value
        )

    if isinstance(value, set):
        frozen = [
            _freeze(item)
            for item in value
        ]

        return tuple(
            sorted(
                frozen,
                key=_canonical_json,
            )
        )

    if (
        value is None
        or isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
            ),
        )
    ):
        return value

    raise TypeError(
        "hypothesis_envelope_unsupported_value:"
        + type(value).__name__
    )


def build_hypothesis_envelope(
    *,
    hypothesis_id: str,
    forecast_id: str,
    world_state_id: str,
    world_state_hash: str,
    frozen_at_ms: int,
    sections: Mapping[str, Any],
    declared_influence_ids: Sequence[str],
    conclusion: HypothesisConclusion,
) -> CanonicalHypothesisEnvelope:

    supplied = set(
        map(str, sections)
    )

    required = set(REQUIRED_SECTIONS)

    missing = sorted(
        required - supplied
    )

    extra = sorted(
        supplied - required
    )

    if missing:
        raise ValueError(
            "hypothesis_envelope_missing_sections:"
            + ",".join(missing)
        )

    if extra:
        raise ValueError(
            "hypothesis_envelope_unknown_sections:"
            + ",".join(extra)
        )

    if conclusion.hypothesis_id != hypothesis_id:
        raise ValueError(
            "hypothesis_envelope_conclusion_hypothesis_mismatch"
        )

    if conclusion.forecast_id != forecast_id:
        raise ValueError(
            "hypothesis_envelope_conclusion_forecast_mismatch"
        )

    declared = tuple(
        sorted(
            set(
                map(
                    str,
                    declared_influence_ids,
                )
            )
        )
    )

    conclusion_influences = tuple(
        sorted(
            set(
                map(
                    str,
                    conclusion.influence_ids,
                )
            )
        )
    )

    if declared != conclusion_influences:
        raise ValueError(
            "hypothesis_envelope_undeclared_influence"
        )

    frozen_sections = {
        name: _freeze(
            sections[name]
        )
        for name in REQUIRED_SECTIONS
    }

    section_digests = {
        name: canonical_digest(
            frozen_sections[name]
        )
        for name in REQUIRED_SECTIONS
    }

    payload = {
        "schema": SCHEMA,
        "hypothesis_id": str(hypothesis_id),
        "forecast_id": str(forecast_id),
        "world_state_id": str(
            world_state_id
        ),
        "world_state_hash": str(
            world_state_hash
        ),
        "frozen_at_ms": int(frozen_at_ms),
        "section_digests":
            section_digests,
        "sections": frozen_sections,
        "declared_influence_ids":
            declared,
        "conclusion":
            conclusion.to_dict(),
        "authority":
            RELATIVE_VALUE_AUTHORITY,
        "execution_eligible": False,
        "promotion_eligible": False,
    }

    payload_digest = canonical_digest(
        payload
    )

    envelope_id = (
        "henv_"
        + payload_digest.split(
            ":",
            1,
        )[1][:32]
    )

    return CanonicalHypothesisEnvelope(
        schema=SCHEMA,
        envelope_id=envelope_id,
        hypothesis_id=str(
            hypothesis_id
        ),
        forecast_id=str(forecast_id),
        world_state_id=str(
            world_state_id
        ),
        world_state_hash=str(
            world_state_hash
        ),
        frozen_at_ms=int(
            frozen_at_ms
        ),
        section_digests=section_digests,
        sections=frozen_sections,
        declared_influence_ids=declared,
        conclusion=conclusion,
        canonical_payload_digest=(
            payload_digest
        ),
        authority=(
            RELATIVE_VALUE_AUTHORITY
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )


def verify_hypothesis_envelope(
    envelope: CanonicalHypothesisEnvelope,
) -> bool:
    rebuilt = build_hypothesis_envelope(
        hypothesis_id=envelope.hypothesis_id,
        forecast_id=envelope.forecast_id,
        world_state_id=envelope.world_state_id,
        world_state_hash=envelope.world_state_hash,
        frozen_at_ms=envelope.frozen_at_ms,
        sections=envelope.sections,
        declared_influence_ids=(
            envelope.declared_influence_ids
        ),
        conclusion=envelope.conclusion,
    )

    return (
        rebuilt.envelope_id
        == envelope.envelope_id
        and rebuilt.canonical_payload_digest
        == envelope.canonical_payload_digest
        and dict(
            rebuilt.section_digests
        )
        == dict(
            envelope.section_digests
        )
    )
