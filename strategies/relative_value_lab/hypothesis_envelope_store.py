"""Immutable persistence for Canonical Hypothesis Envelopes."""

from __future__ import annotations

import json
from pathlib import Path

from .hypothesis_envelope import (
    CanonicalHypothesisEnvelope,
)
from .hypothesis_envelope_replay import (
    envelope_from_dict,
    replay_conclusion_bytes,
)


def envelope_path(
    root: Path,
    envelope_id: str,
) -> Path:
    return (
        Path(root)
        / f"{envelope_id}.json"
    )


def persist_envelope(
    *,
    root: Path,
    envelope: CanonicalHypothesisEnvelope,
) -> Path:
    """Persist canonical bytes exactly once."""

    root = Path(root)
    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = envelope_path(
        root,
        envelope.envelope_id,
    )

    if path.exists():
        raise FileExistsError(
            "hypothesis_envelope_already_persisted:"
            + envelope.envelope_id
        )

    raw = envelope.canonical_bytes()

    # Ensure canonical bytes are valid JSON before persistence.
    json.loads(
        raw.decode("utf-8")
    )

    path.write_bytes(raw)

    return path


def load_persisted_envelope(
    path: Path,
) -> CanonicalHypothesisEnvelope:
    raw = Path(path).read_bytes()

    payload = json.loads(
        raw.decode("utf-8")
    )

    envelope = envelope_from_dict(
        payload
    )

    # Stored bytes themselves must be canonical.
    if envelope.canonical_bytes() != raw:
        raise ValueError(
            "persisted_hypothesis_envelope_not_canonical"
        )

    return envelope


def replay_persisted_conclusion_bytes(
    path: Path,
) -> bytes:
    envelope = load_persisted_envelope(
        path
    )

    return replay_conclusion_bytes(
        envelope
    )
