from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from statistics import NormalDist, mean
from typing import Any, Iterable, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class StatisticalEvidence:
    evidence_id: str
    scope: str
    observed_at_ms: int
    available_at_ms: int
    realized_bps: float
    positive: bool
    evidence_root: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if int(self.available_at_ms) < int(self.observed_at_ms):
            raise ValueError("statistical_evidence_available_before_observation")
        if not str(self.evidence_root).startswith("sha256:"):
            raise ValueError("statistical_evidence_root_unbound")
        if float(self.weight) <= 0.0:
            raise ValueError("statistical_evidence_weight_must_be_positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StatisticsSnapshot:
    schema: str
    snapshot_id: str
    scope: str
    as_of_ms: int
    evidence_cutoff_ms: int | None
    n: int
    effective_n: float
    wins: int
    losses: int
    mean_bps: float | None
    variance_bps2: float | None
    std_bps: float | None
    win_rate: float | None
    posterior_win_probability: float
    posterior_win_interval_90: tuple[float, float]
    posterior_edge_positive_probability: float | None
    recent_mean_bps: float | None
    prior_mean_bps: float | None
    change_point_pressure: float
    source_evidence_ids: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.evidence_cutoff_ms is not None and int(self.evidence_cutoff_ms) >= int(self.as_of_ms):
            raise ValueError("statistics_snapshot_future_or_same_time_evidence")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("statistics_snapshot_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProbabilisticSynthesisState:
    schema: str
    state_id: str
    as_of_ms: int
    exact_scope: str
    contributing_scopes: tuple[str, ...]
    hierarchical_win_probability: float
    hierarchical_edge_positive_probability: float | None
    uncertainty: float
    change_point_probability: float
    effective_sample_size: float
    scope_weights: Mapping[str, float]
    source_snapshot_ids: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.hierarchical_win_probability,
            self.uncertainty,
            self.change_point_probability,
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError("probabilistic_synthesis_probability_out_of_range")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("probabilistic_synthesis_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scope_weights"] = dict(self.scope_weights)
        return payload


class StatisticsBee:
    """Continuously accumulates causally available evidence into sufficient statistics.

    Evidence is never used at or before its availability timestamp. A snapshot at
    T therefore contains only evidence with available_at_ms < T.
    """

    version = "hivenance.statistics_bee.v1"

    def __init__(self, *, beta_alpha: float = 2.0, beta_beta: float = 2.0) -> None:
        self.beta_alpha = float(beta_alpha)
        self.beta_beta = float(beta_beta)
        self._rows: list[StatisticalEvidence] = []

    def ingest(self, evidence: StatisticalEvidence) -> None:
        self._rows.append(evidence)

    def ingest_many(self, rows: Iterable[StatisticalEvidence]) -> None:
        for row in rows:
            self.ingest(row)

    def snapshot(
        self,
        *,
        scope: str,
        as_of_ms: int,
        max_age_ms: int | None = None,
        recent_fraction: float = 0.35,
    ) -> StatisticsSnapshot:
        cutoff_floor = None if max_age_ms is None else int(as_of_ms) - int(max_age_ms)
        rows = [
            row
            for row in self._rows
            if row.scope == str(scope)
            and int(row.available_at_ms) < int(as_of_ms)
            and (cutoff_floor is None or int(row.available_at_ms) >= cutoff_floor)
        ]
        rows.sort(key=lambda row: (row.available_at_ms, row.evidence_id))

        n = len(rows)
        total_weight = sum(float(row.weight) for row in rows)
        wins = sum(1 for row in rows if row.positive)
        losses = n - wins
        weighted_mean = (
            sum(float(row.realized_bps) * float(row.weight) for row in rows) / total_weight
            if total_weight > 0
            else None
        )
        variance = None
        std = None
        if total_weight > 0 and weighted_mean is not None:
            variance = sum(
                float(row.weight) * (float(row.realized_bps) - weighted_mean) ** 2
                for row in rows
            ) / total_weight
            std = math.sqrt(max(0.0, variance))

        alpha = self.beta_alpha + sum(float(row.weight) for row in rows if row.positive)
        beta = self.beta_beta + sum(float(row.weight) for row in rows if not row.positive)
        posterior_win = alpha / max(1e-12, alpha + beta)
        beta_var = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
        beta_sd = math.sqrt(max(0.0, beta_var))
        z90 = 1.6448536269514722
        win_interval = (
            max(0.0, posterior_win - z90 * beta_sd),
            min(1.0, posterior_win + z90 * beta_sd),
        )

        edge_prob = None
        if n >= 2 and weighted_mean is not None and std is not None:
            if std <= 1e-12:
                edge_prob = 1.0 if weighted_mean > 0 else (0.0 if weighted_mean < 0 else 0.5)
            else:
                se = std / math.sqrt(max(1.0, total_weight))
                edge_prob = NormalDist(mu=weighted_mean, sigma=max(1e-12, se)).cdf(float("inf")) - NormalDist(
                    mu=weighted_mean, sigma=max(1e-12, se)
                ).cdf(0.0)

        recent_mean = prior_mean = None
        change_pressure = 0.0
        if n >= 4:
            split = max(1, min(n - 1, int(round(n * (1.0 - float(recent_fraction))))))
            prior = rows[:split]
            recent = rows[split:]
            prior_mean = mean(float(row.realized_bps) for row in prior)
            recent_mean = mean(float(row.realized_bps) for row in recent)
            scale = max(
                1.0,
                std or 0.0,
                abs(prior_mean) * 0.25,
            )
            change_pressure = max(0.0, min(1.0, abs(recent_mean - prior_mean) / (2.0 * scale)))

        body = {
            "scope": str(scope),
            "as_of_ms": int(as_of_ms),
            "cutoff": rows[-1].available_at_ms if rows else None,
            "evidence_ids": [row.evidence_id for row in rows],
            "posterior_win_probability": posterior_win,
            "change_point_pressure": change_pressure,
        }
        return StatisticsSnapshot(
            schema="hivenance_statistics_snapshot_v1",
            snapshot_id="stat_" + _digest(body).split(":", 1)[1][:24],
            scope=str(scope),
            as_of_ms=int(as_of_ms),
            evidence_cutoff_ms=(int(rows[-1].available_at_ms) if rows else None),
            n=n,
            effective_n=round(total_weight, 8),
            wins=wins,
            losses=losses,
            mean_bps=None if weighted_mean is None else round(weighted_mean, 8),
            variance_bps2=None if variance is None else round(variance, 8),
            std_bps=None if std is None else round(std, 8),
            win_rate=None if n == 0 else round(wins / n, 8),
            posterior_win_probability=round(posterior_win, 8),
            posterior_win_interval_90=(round(win_interval[0], 8), round(win_interval[1], 8)),
            posterior_edge_positive_probability=None if edge_prob is None else round(edge_prob, 8),
            recent_mean_bps=None if recent_mean is None else round(recent_mean, 8),
            prior_mean_bps=None if prior_mean is None else round(prior_mean, 8),
            change_point_pressure=round(change_pressure, 8),
            source_evidence_ids=tuple(row.evidence_id for row in rows),
            evidence_roots=tuple(sorted({row.evidence_root for row in rows})),
        )


class SynthesisBee:
    """Combines exact and broader statistics without pretending they are equivalent."""

    version = "hivenance.synthesis_bee.v1"

    def synthesize(
        self,
        *,
        exact: StatisticsSnapshot,
        broader: Sequence[tuple[StatisticsSnapshot, float]] = (),
    ) -> ProbabilisticSynthesisState:
        snapshots: list[tuple[StatisticsSnapshot, float]] = [(exact, 1.0)]
        snapshots.extend((snap, max(0.0, float(weight))) for snap, weight in broader)

        usable = [(snap, specificity) for snap, specificity in snapshots if snap.n > 0 and specificity > 0.0]
        if not usable:
            usable = [(exact, 1.0)]

        raw_weights: dict[str, float] = {}
        for snap, specificity in usable:
            evidence_strength = math.sqrt(max(0.0, float(snap.effective_n)))
            raw_weights[snap.scope] = specificity * evidence_strength

        total_weight = sum(raw_weights.values())
        if total_weight <= 0.0:
            normalized = {exact.scope: 1.0}
        else:
            normalized = {scope: value / total_weight for scope, value in raw_weights.items()}

        win_probability = sum(
            normalized.get(snap.scope, 0.0) * float(snap.posterior_win_probability)
            for snap, _ in usable
        )
        edge_terms = [
            (normalized.get(snap.scope, 0.0), snap.posterior_edge_positive_probability)
            for snap, _ in usable
            if snap.posterior_edge_positive_probability is not None
        ]
        edge_probability = (
            sum(weight * float(value) for weight, value in edge_terms) /
            max(1e-12, sum(weight for weight, _ in edge_terms))
            if edge_terms
            else None
        )

        posterior_variance = sum(
            normalized.get(snap.scope, 0.0)
            * (float(snap.posterior_win_probability) - win_probability) ** 2
            for snap, _ in usable
        )
        scarcity = 1.0 / math.sqrt(1.0 + sum(float(snap.effective_n) for snap, _ in usable))
        uncertainty = max(0.0, min(1.0, 0.65 * scarcity + 0.35 * min(1.0, math.sqrt(posterior_variance) * 2.0)))
        change_probability = max(float(snap.change_point_pressure) for snap, _ in usable)

        roots = tuple(sorted({root for snap, _ in usable for root in snap.evidence_roots}))
        state_body = {
            "as_of_ms": exact.as_of_ms,
            "exact_scope": exact.scope,
            "snapshots": [snap.snapshot_id for snap, _ in usable],
            "weights": normalized,
        }
        return ProbabilisticSynthesisState(
            schema="hivenance_probabilistic_synthesis_state_v1",
            state_id="synstat_" + _digest(state_body).split(":", 1)[1][:24],
            as_of_ms=int(exact.as_of_ms),
            exact_scope=exact.scope,
            contributing_scopes=tuple(snap.scope for snap, _ in usable),
            hierarchical_win_probability=round(win_probability, 8),
            hierarchical_edge_positive_probability=None if edge_probability is None else round(edge_probability, 8),
            uncertainty=round(uncertainty, 8),
            change_point_probability=round(change_probability, 8),
            effective_sample_size=round(sum(float(snap.effective_n) for snap, _ in usable), 8),
            scope_weights={key: round(value, 8) for key, value in normalized.items()},
            source_snapshot_ids=tuple(snap.snapshot_id for snap, _ in usable),
            evidence_roots=roots,
        )
