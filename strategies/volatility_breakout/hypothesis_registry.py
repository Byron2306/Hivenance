from __future__ import annotations

"""Pre-registration for new (not-yet-tested) trading hypotheses.

Research pipelines that mine historical forecasts can silently p-hack: a
"hypothesis" gets declared only after its authors have already seen how it
performs on the very data used to judge it. This module gives Phase-2/Phase-3
research an immutable, timestamped, hash-locked record of what a hypothesis
predicts *before* any forecast attributed to it is allowed to count as
evidence, so later validation can distinguish genuine out-of-sample results
from post-hoc data mining.

This module does not judge whether a hypothesis is good, nor does it wire
into live trading in any way. It only proves, after the fact, that a
hypothesis specification existed and was frozen before a given forecast was
produced.
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

REGISTRY_SCHEMA = "hivenance_hypothesis_pre_registration_v1"


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class PreRegisteredHypothesis:
    hypothesis_id: str
    title: str
    description: str
    symbols: tuple[str, ...]
    directions: tuple[str, ...]
    entry_rule_summary: str
    exit_rule_summary: str
    predicted_edge_bps: float
    predicted_edge_rationale: str
    registered_at: float
    registered_by: str
    spec_sha256: str
    schema: str = REGISTRY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _spec_payload(
    *,
    hypothesis_id: str,
    title: str,
    description: str,
    symbols: tuple[str, ...],
    directions: tuple[str, ...],
    entry_rule_summary: str,
    exit_rule_summary: str,
    predicted_edge_bps: float,
    predicted_edge_rationale: str,
    registered_by: str,
) -> dict[str, Any]:
    return {
        "schema": REGISTRY_SCHEMA,
        "hypothesis_id": hypothesis_id,
        "title": title,
        "description": description,
        "symbols": list(symbols),
        "directions": list(directions),
        "entry_rule_summary": entry_rule_summary,
        "exit_rule_summary": exit_rule_summary,
        "predicted_edge_bps": float(predicted_edge_bps),
        "predicted_edge_rationale": predicted_edge_rationale,
        "registered_by": registered_by,
    }


def register_hypothesis(
    *,
    registry_dir: Path,
    hypothesis_id: str,
    title: str,
    description: str,
    symbols: tuple[str, ...],
    directions: tuple[str, ...],
    entry_rule_summary: str,
    exit_rule_summary: str,
    predicted_edge_bps: float,
    predicted_edge_rationale: str,
    registered_by: str,
    now_fn=time.time,
) -> PreRegisteredHypothesis:
    """Freeze a new hypothesis spec to disk before any forecast is generated.

    Raises FileExistsError if hypothesis_id is already registered: a
    pre-registration must never be silently overwritten or edited after the
    fact, since that would defeat its entire purpose. Register a new
    hypothesis_id (e.g. with a version suffix) if the design changes.
    """
    registry_dir.mkdir(parents=True, exist_ok=True)
    out_path = registry_dir / f"{hypothesis_id}.json"
    if out_path.exists():
        raise FileExistsError(
            f"hypothesis '{hypothesis_id}' is already pre-registered at {out_path}; "
            "pre-registrations are immutable. Register a new hypothesis_id instead."
        )
    payload = _spec_payload(
        hypothesis_id=hypothesis_id,
        title=title,
        description=description,
        symbols=symbols,
        directions=directions,
        entry_rule_summary=entry_rule_summary,
        exit_rule_summary=exit_rule_summary,
        predicted_edge_bps=predicted_edge_bps,
        predicted_edge_rationale=predicted_edge_rationale,
        registered_by=registered_by,
    )
    record = PreRegisteredHypothesis(
        hypothesis_id=hypothesis_id,
        title=title,
        description=description,
        symbols=tuple(symbols),
        directions=tuple(directions),
        entry_rule_summary=entry_rule_summary,
        exit_rule_summary=exit_rule_summary,
        predicted_edge_bps=float(predicted_edge_bps),
        predicted_edge_rationale=predicted_edge_rationale,
        registered_at=float(now_fn()),
        registered_by=registered_by,
        spec_sha256=canonical_hash(payload),
    )
    out_path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    return record


def load_hypothesis(registry_dir: Path, hypothesis_id: str) -> Optional[PreRegisteredHypothesis]:
    path = registry_dir / f"{hypothesis_id}.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    return PreRegisteredHypothesis(
        hypothesis_id=payload["hypothesis_id"],
        title=payload["title"],
        description=payload["description"],
        symbols=tuple(payload.get("symbols") or ()),
        directions=tuple(payload.get("directions") or ()),
        entry_rule_summary=payload.get("entry_rule_summary", ""),
        exit_rule_summary=payload.get("exit_rule_summary", ""),
        predicted_edge_bps=float(payload.get("predicted_edge_bps") or 0.0),
        predicted_edge_rationale=payload.get("predicted_edge_rationale", ""),
        registered_at=float(payload.get("registered_at") or 0.0),
        registered_by=payload.get("registered_by", ""),
        spec_sha256=payload.get("spec_sha256", ""),
        schema=payload.get("schema", REGISTRY_SCHEMA),
    )


def load_all_hypotheses(registry_dir: Path) -> list[PreRegisteredHypothesis]:
    if not registry_dir.exists():
        return []
    out: list[PreRegisteredHypothesis] = []
    for path in sorted(registry_dir.glob("*.json")):
        hyp = load_hypothesis(registry_dir, path.stem)
        if hyp is not None:
            out.append(hyp)
    return out


def is_out_of_sample(hypothesis: PreRegisteredHypothesis, forecast_created_ts: float) -> bool:
    """True only if the forecast was produced strictly after pre-registration.

    A forecast timestamped at or before registered_at could have influenced
    (or been influenced by) the decision to register this hypothesis, so it
    must never count as confirming evidence of edge.
    """
    return float(forecast_created_ts) > float(hypothesis.registered_at)
