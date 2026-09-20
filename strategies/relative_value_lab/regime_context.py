from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class RegimeContext:
    schema: str
    context_id: str
    as_of_ms: int
    deterministic_hint: str
    deterministic_confidence: float
    bayesian_probabilities: Mapping[str, float]
    dominant_posterior_regime: str | None
    posterior_entropy: float | None
    change_point_probability: float
    disagreement_score: float
    evidence_cutoff_ms: int | None
    provenance: Mapping[str, Any]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("regime_context_authority_escalation_forbidden")
        if not 0.0 <= float(self.deterministic_confidence) <= 1.0:
            raise ValueError("regime_context_deterministic_confidence_out_of_range")
        if not 0.0 <= float(self.change_point_probability) <= 1.0:
            raise ValueError("regime_context_change_probability_out_of_range")
        if not 0.0 <= float(self.disagreement_score) <= 1.0:
            raise ValueError("regime_context_disagreement_out_of_range")
        if self.evidence_cutoff_ms is not None and int(self.evidence_cutoff_ms) >= int(self.as_of_ms):
            raise ValueError("regime_context_future_or_same_time_evidence")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bayesian_probabilities"] = dict(self.bayesian_probabilities)
        payload["provenance"] = dict(self.provenance)
        return payload


_DETERMINISTIC_TO_BAYES = {
    "trend_expansion": "TREND",
    "stretch_exhaustion": "MEAN_REVERSION",
    "quiet_range": "MEAN_REVERSION",
    "balanced_transition": "TRANSITION",
    "hostile_liquidity": "STRESS",
}


def build_regime_context(
    *,
    as_of_ms: int,
    deterministic: Mapping[str, Any] | None = None,
    bayesian: Mapping[str, Any] | None = None,
) -> RegimeContext:
    deterministic = dict(deterministic or {})
    bayesian = dict(bayesian or {})

    hint = str(deterministic.get("regime_hint") or "unknown")
    confidence = max(0.0, min(1.0, float(deterministic.get("confidence") or 0.0)))

    probabilities = bayesian.get("probabilities")
    if not isinstance(probabilities, Mapping):
        probabilities = {}
    probabilities = {
        str(k): max(0.0, min(1.0, float(v)))
        for k, v in probabilities.items()
    }

    dominant = bayesian.get("dominant_regime")
    dominant = None if dominant is None else str(dominant)
    entropy = bayesian.get("entropy")
    entropy = None if entropy is None else max(0.0, min(1.0, float(entropy)))
    change = max(0.0, min(1.0, float(bayesian.get("change_point_probability") or 0.0)))
    cutoff = bayesian.get("evidence_available_at_ms")
    cutoff = None if cutoff is None else int(cutoff)

    mapped = _DETERMINISTIC_TO_BAYES.get(hint)
    disagreement = 0.0
    if mapped and probabilities:
        mapped_probability = float(probabilities.get(mapped, 0.0))
        disagreement = confidence * (1.0 - mapped_probability)
    elif mapped and dominant:
        disagreement = confidence if dominant != mapped else 0.0

    provenance = {
        "deterministic_source": deterministic.get("source") or "feature_engine",
        "bayesian_posterior_id": bayesian.get("posterior_id"),
        "bayesian_schema": bayesian.get("schema"),
    }

    body = {
        "as_of_ms": int(as_of_ms),
        "deterministic_hint": hint,
        "deterministic_confidence": confidence,
        "bayesian_probabilities": probabilities,
        "dominant": dominant,
        "entropy": entropy,
        "change": change,
        "disagreement": disagreement,
        "cutoff": cutoff,
        "provenance": provenance,
    }
    return RegimeContext(
        schema="hivenance_regime_context_v1",
        context_id="rctxreg_" + _digest(body).split(":", 1)[1][:24],
        as_of_ms=int(as_of_ms),
        deterministic_hint=hint,
        deterministic_confidence=round(confidence, 8),
        bayesian_probabilities={k: round(v, 8) for k, v in probabilities.items()},
        dominant_posterior_regime=dominant,
        posterior_entropy=None if entropy is None else round(entropy, 8),
        change_point_probability=round(change, 8),
        disagreement_score=round(max(0.0, min(1.0, disagreement)), 8),
        evidence_cutoff_ms=cutoff,
        provenance=provenance,
    )
