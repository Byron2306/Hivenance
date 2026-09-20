from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _normalize(values: Mapping[str, float], states: Sequence[str]) -> dict[str, float]:
    clean = {state: max(0.0, float(values.get(state, 0.0))) for state in states}
    total = sum(clean.values())
    if total <= 0.0:
        return {state: 1.0 / len(states) for state in states}
    return {state: clean[state] / total for state in states}


@dataclass(frozen=True)
class RegimePosterior:
    schema: str
    posterior_id: str
    as_of_ms: int
    evidence_available_at_ms: int
    probabilities: Mapping[str, float]
    dominant_regime: str
    entropy: float
    change_point_probability: float
    previous_posterior_id: str | None
    source_evidence_ids: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if int(self.evidence_available_at_ms) >= int(self.as_of_ms):
            raise ValueError("regime_posterior_requires_prior_evidence")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("regime_posterior_authority_escalation_forbidden")
        if abs(sum(float(x) for x in self.probabilities.values()) - 1.0) > 1e-6:
            raise ValueError("regime_posterior_not_normalized")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["probabilities"] = dict(self.probabilities)
        return payload


class BayesianRegimeFilter:
    """Small local Bayesian regime filter with an explicit transition model.

    Input likelihoods are research evidence, not decisions. The filter maintains
    a posterior over regimes and exposes posterior movement as change pressure.
    """

    version = "hivenance.bayesian_regime_filter.v1"
    DEFAULT_STATES = ("TREND", "MEAN_REVERSION", "TRANSITION", "STRESS")

    def __init__(
        self,
        *,
        states: Sequence[str] = DEFAULT_STATES,
        transition_matrix: Mapping[str, Mapping[str, float]] | None = None,
        prior: Mapping[str, float] | None = None,
    ) -> None:
        self.states = tuple(str(x) for x in states)
        if not self.states:
            raise ValueError("regime_filter_states_missing")

        if transition_matrix is None:
            off = 0.18 / max(1, len(self.states) - 1)
            transition_matrix = {
                source: {
                    target: (0.82 if source == target else off)
                    for target in self.states
                }
                for source in self.states
            }

        self.transition = {
            source: _normalize(transition_matrix.get(source, {}), self.states)
            for source in self.states
        }
        self.posterior = _normalize(prior or {}, self.states)
        self.last: RegimePosterior | None = None

    def update(
        self,
        *,
        likelihoods: Mapping[str, float],
        as_of_ms: int,
        evidence_available_at_ms: int,
        source_evidence_ids: Sequence[str],
        evidence_roots: Sequence[str],
    ) -> RegimePosterior:
        if int(evidence_available_at_ms) >= int(as_of_ms):
            raise ValueError("regime_filter_future_or_same_time_evidence")
        roots = tuple(sorted(set(str(x) for x in evidence_roots)))
        if not roots or any(not root.startswith("sha256:") for root in roots):
            raise ValueError("regime_filter_evidence_root_unbound")

        previous = dict(self.posterior)
        predicted = {
            target: sum(
                previous[source] * self.transition[source][target]
                for source in self.states
            )
            for target in self.states
        }

        raw = {
            state: predicted[state] * max(1e-9, float(likelihoods.get(state, 1e-9)))
            for state in self.states
        }
        posterior = _normalize(raw, self.states)

        l1_shift = 0.5 * sum(abs(posterior[state] - previous[state]) for state in self.states)
        transition_mass = posterior.get("TRANSITION", 0.0)
        change_probability = max(0.0, min(1.0, max(l1_shift, transition_mass)))

        entropy_raw = -sum(
            probability * math.log(max(1e-12, probability))
            for probability in posterior.values()
        )
        entropy = entropy_raw / math.log(len(self.states)) if len(self.states) > 1 else 0.0

        dominant = max(self.states, key=lambda state: posterior[state])
        body = {
            "as_of_ms": int(as_of_ms),
            "available_at_ms": int(evidence_available_at_ms),
            "probabilities": posterior,
            "previous": self.last.posterior_id if self.last else None,
            "source_evidence_ids": sorted(set(str(x) for x in source_evidence_ids)),
            "evidence_roots": roots,
        }
        result = RegimePosterior(
            schema="hivenance_regime_posterior_v1",
            posterior_id="reg_" + _digest(body).split(":", 1)[1][:24],
            as_of_ms=int(as_of_ms),
            evidence_available_at_ms=int(evidence_available_at_ms),
            probabilities={key: round(value, 8) for key, value in posterior.items()},
            dominant_regime=dominant,
            entropy=round(entropy, 8),
            change_point_probability=round(change_probability, 8),
            previous_posterior_id=self.last.posterior_id if self.last else None,
            source_evidence_ids=tuple(sorted(set(str(x) for x in source_evidence_ids))),
            evidence_roots=roots,
        )
        self.posterior = dict(result.probabilities)
        self.last = result
        return result
