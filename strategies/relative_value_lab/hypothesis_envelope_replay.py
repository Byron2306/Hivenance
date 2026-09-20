"""Deterministic replay for Canonical Hypothesis Envelopes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from .hypothesis_envelope import (
    CanonicalHypothesisEnvelope,
    HypothesisConclusion,
    build_hypothesis_envelope,
    verify_hypothesis_envelope,
)


def replay_conclusion(
    envelope: CanonicalHypothesisEnvelope,
) -> HypothesisConclusion:
    """Return the exact frozen conclusion encoded by the envelope."""

    if not verify_hypothesis_envelope(envelope):
        raise ValueError(
            "hypothesis_envelope_verification_failed"
        )

    conclusion = envelope.conclusion

    return HypothesisConclusion(
        hypothesis_id=conclusion.hypothesis_id,
        forecast_id=conclusion.forecast_id,
        symbol=conclusion.symbol,
        timestamp_ms=conclusion.timestamp_ms,
        horizon_seconds=conclusion.horizon_seconds,
        direction=conclusion.direction,
        abstain=conclusion.abstain,
        expected_move_bps=conclusion.expected_move_bps,
        expected_cost_bps=conclusion.expected_cost_bps,
        expected_net_bps=conclusion.expected_net_bps,
        uncertainty=conclusion.uncertainty,
        influence_ids=tuple(
            conclusion.influence_ids
        ),
        authority=conclusion.authority,
        execution_eligible=False,
        promotion_eligible=False,
    )


def replay_conclusion_bytes(
    envelope: CanonicalHypothesisEnvelope,
) -> bytes:
    conclusion = replay_conclusion(
        envelope
    )

    from .hypothesis_envelope import (
        _canonical_json,
    )

    return _canonical_json(
        conclusion.to_dict()
    ).encode("utf-8")


def envelope_from_dict(
    payload: Mapping[str, Any],
) -> CanonicalHypothesisEnvelope:
    """Deserialize and revalidate an envelope from stored canonical data."""

    conclusion_raw = dict(
        payload["conclusion"]
    )

    conclusion = HypothesisConclusion(
        hypothesis_id=str(
            conclusion_raw["hypothesis_id"]
        ),
        forecast_id=str(
            conclusion_raw["forecast_id"]
        ),
        symbol=str(
            conclusion_raw["symbol"]
        ),
        timestamp_ms=int(
            conclusion_raw["timestamp_ms"]
        ),
        horizon_seconds=int(
            conclusion_raw["horizon_seconds"]
        ),
        direction=str(
            conclusion_raw["direction"]
        ),
        abstain=bool(
            conclusion_raw["abstain"]
        ),
        expected_move_bps=(
            conclusion_raw.get(
                "expected_move_bps"
            )
        ),
        expected_cost_bps=(
            conclusion_raw.get(
                "expected_cost_bps"
            )
        ),
        expected_net_bps=(
            conclusion_raw.get(
                "expected_net_bps"
            )
        ),
        uncertainty=(
            conclusion_raw.get(
                "uncertainty"
            )
        ),
        influence_ids=tuple(
            conclusion_raw.get(
                "influence_ids",
                (),
            )
        ),
        authority=str(
            conclusion_raw.get(
                "authority"
            )
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )

    rebuilt = build_hypothesis_envelope(
        hypothesis_id=str(
            payload["hypothesis_id"]
        ),
        forecast_id=str(
            payload["forecast_id"]
        ),
        world_state_id=str(
            payload["world_state_id"]
        ),
        world_state_hash=str(
            payload["world_state_hash"]
        ),
        frozen_at_ms=int(
            payload["frozen_at_ms"]
        ),
        sections=dict(
            payload["sections"]
        ),
        declared_influence_ids=tuple(
            payload.get(
                "declared_influence_ids",
                (),
            )
        ),
        conclusion=conclusion,
    )

    if (
        rebuilt.envelope_id
        != payload.get("envelope_id")
    ):
        raise ValueError(
            "hypothesis_envelope_id_mismatch"
        )

    if (
        rebuilt.canonical_payload_digest
        != payload.get(
            "canonical_payload_digest"
        )
    ):
        raise ValueError(
            "hypothesis_envelope_digest_mismatch"
        )

    expected_section_digests = dict(
        payload.get(
            "section_digests",
            {},
        )
    )

    if (
        dict(rebuilt.section_digests)
        != expected_section_digests
    ):
        raise ValueError(
            "hypothesis_envelope_section_digest_mismatch"
        )

    return rebuilt
