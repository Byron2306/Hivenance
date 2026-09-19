from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .world_graph import WorldGraph, WorldGraphNode


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ComparisonReference:
    reference_id: str
    observed_at_ms: int
    symbol: str
    utc_hour: int
    features: Mapping[str, float | int | str | None]
    evidence_roots: tuple[str, ...]
    selected: bool | None = None
    event_label: str | None = None


@dataclass(frozen=True)
class ComparisonResult:
    schema: str
    comparison_id: str
    comparison_type: str
    observed_at_ms: int
    symbol: str
    reference_ids: tuple[str, ...]
    metrics: Mapping[str, Any]
    evidence_roots: tuple[str, ...]
    matched_n: int
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComparisonEngine:
    """Timestamp-safe observed comparisons. Never emits a trade direction."""

    version = "hivenance.comparison_engine.v1"

    @staticmethod
    def _prior(
        references: Sequence[ComparisonReference],
        observed_at_ms: int,
    ) -> list[ComparisonReference]:
        return [r for r in references if int(r.observed_at_ms) < int(observed_at_ms)]

    def same_utc_hour_baseline(
        self,
        *,
        observed_at_ms: int,
        symbol: str,
        utc_hour: int,
        current_features: Mapping[str, float | int | str | None],
        references: Sequence[ComparisonReference],
        feature_names: Sequence[str],
    ) -> ComparisonResult:
        matched = [
            r for r in self._prior(references, observed_at_ms)
            if r.symbol == symbol and int(r.utc_hour) == int(utc_hour)
        ]
        metrics: dict[str, Any] = {}
        for name in feature_names:
            current = current_features.get(name)
            vals = [
                float(r.features[name])
                for r in matched
                if isinstance(r.features.get(name), (int, float))
                and math.isfinite(float(r.features[name]))
            ]
            if isinstance(current, (int, float)) and vals:
                med = statistics.median(vals)
                metrics[name] = {
                    "current": float(current),
                    "reference_median": med,
                    "delta": float(current) - med,
                    "reference_n": len(vals),
                }
            else:
                metrics[name] = {"current": current, "reference_median": None, "delta": None, "reference_n": len(vals)}
        return self._result(
            "SELF_SAME_UTC_HOUR",
            observed_at_ms, symbol, matched, metrics,
        )

    def cross_section(
        self,
        *,
        observed_at_ms: int,
        symbol: str,
        current_features: Mapping[str, float | int | str | None],
        peers: Sequence[ComparisonReference],
        feature_names: Sequence[str],
        tolerance_ms: int = 60_000,
    ) -> ComparisonResult:
        matched = [
            r for r in peers
            if r.symbol != symbol
            and int(r.observed_at_ms) <= int(observed_at_ms)
            and int(observed_at_ms) - int(r.observed_at_ms) <= int(tolerance_ms)
        ]
        metrics: dict[str, Any] = {}
        for name in feature_names:
            current = current_features.get(name)
            vals = [
                float(r.features[name])
                for r in matched
                if isinstance(r.features.get(name), (int, float))
                and math.isfinite(float(r.features[name]))
            ]
            med = statistics.median(vals) if vals else None
            metrics[name] = {
                "current": float(current) if isinstance(current, (int, float)) else current,
                "peer_median": med,
                "delta": (float(current) - med) if isinstance(current, (int, float)) and med is not None else None,
                "peer_n": len(vals),
            }
        return self._result("CROSS_SECTION", observed_at_ms, symbol, matched, metrics)

    def selected_vs_rejected(
        self,
        *,
        observed_at_ms: int,
        symbol: str,
        references: Sequence[ComparisonReference],
        feature_names: Sequence[str],
    ) -> ComparisonResult:
        prior = self._prior(references, observed_at_ms)
        selected = [r for r in prior if r.selected is True]
        rejected = [r for r in prior if r.selected is False]
        metrics: dict[str, Any] = {}
        for name in feature_names:
            a = [float(r.features[name]) for r in selected if isinstance(r.features.get(name), (int, float))]
            b = [float(r.features[name]) for r in rejected if isinstance(r.features.get(name), (int, float))]
            metrics[name] = {
                "selected_median": statistics.median(a) if a else None,
                "rejected_median": statistics.median(b) if b else None,
                "delta": (statistics.median(a) - statistics.median(b)) if a and b else None,
                "selected_n": len(a),
                "rejected_n": len(b),
            }
        return self._result("SELECTED_VS_REJECTED", observed_at_ms, symbol, selected + rejected, metrics)

    def event_vs_control(
        self,
        *,
        observed_at_ms: int,
        symbol: str,
        references: Sequence[ComparisonReference],
        event_label: str,
        control_label: str,
        feature_names: Sequence[str],
    ) -> ComparisonResult:
        prior = self._prior(references, observed_at_ms)
        events = [r for r in prior if r.event_label == event_label]
        controls = [r for r in prior if r.event_label == control_label]
        metrics: dict[str, Any] = {}
        for name in feature_names:
            a = [float(r.features[name]) for r in events if isinstance(r.features.get(name), (int, float))]
            b = [float(r.features[name]) for r in controls if isinstance(r.features.get(name), (int, float))]
            metrics[name] = {
                "event_median": statistics.median(a) if a else None,
                "control_median": statistics.median(b) if b else None,
                "delta": (statistics.median(a) - statistics.median(b)) if a and b else None,
                "event_n": len(a),
                "control_n": len(b),
            }
        return self._result("EVENT_VS_CONTROL", observed_at_ms, symbol, events + controls, metrics)

    def nearest_prior_states(
        self,
        *,
        observed_at_ms: int,
        symbol: str,
        current_features: Mapping[str, float | int | str | None],
        references: Sequence[ComparisonReference],
        feature_names: Sequence[str],
        k: int = 10,
    ) -> ComparisonResult:
        candidates = self._prior(references, observed_at_ms)
        scored: list[tuple[float, ComparisonReference]] = []
        for r in candidates:
            diffs = []
            for name in feature_names:
                a = current_features.get(name)
                b = r.features.get(name)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    diffs.append((float(a) - float(b)) ** 2)
            if diffs:
                scored.append((sum(diffs) / len(diffs), r))
        scored.sort(key=lambda x: (x[0], x[1].observed_at_ms, x[1].reference_id))
        matched = [r for _, r in scored[: max(1, int(k))]]
        metrics = {
            "distance_mean": statistics.fmean([d for d, _ in scored[: max(1, int(k))]]) if scored else None,
            "features": tuple(feature_names),
        }
        return self._result("NEAREST_PRIOR_STATES", observed_at_ms, symbol, matched, metrics)

    def _result(
        self,
        comparison_type: str,
        observed_at_ms: int,
        symbol: str,
        matched: Sequence[ComparisonReference],
        metrics: Mapping[str, Any],
    ) -> ComparisonResult:
        roots = tuple(sorted({root for r in matched for root in r.evidence_roots}))
        ids = tuple(r.reference_id for r in matched)
        body = {
            "type": comparison_type,
            "observed_at_ms": int(observed_at_ms),
            "symbol": symbol,
            "reference_ids": ids,
            "metrics": metrics,
            "evidence_roots": roots,
        }
        return ComparisonResult(
            schema="hivenance_comparison_result_v1",
            comparison_id="cmp_" + _digest(body).split(":", 1)[1][:24],
            comparison_type=comparison_type,
            observed_at_ms=int(observed_at_ms),
            symbol=str(symbol),
            reference_ids=ids,
            metrics=dict(metrics),
            evidence_roots=roots,
            matched_n=len(matched),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )


def add_comparison_result(
    graph: WorldGraph,
    *,
    result: ComparisonResult,
    created_at_ms: int,
) -> WorldGraphNode:
    if not result.evidence_roots:
        # No matches is itself useful missing-comparison information, but it must
        # not manufacture an independent evidence root.
        roots = ()
    else:
        roots = result.evidence_roots
    return graph.add_node(
        organ_id="comparison_engine",
        family="COMPARISON",
        created_at_ms=created_at_ms,
        evidence_roots=roots,
        lineage_id="hivenance.comparison_engine.v1",
        transformation_id=f"comparison.{result.comparison_type.lower()}.v1",
        payload=result.to_dict(),
        freshness=1.0,
        uncertainty=1.0 if result.matched_n == 0 else min(1.0, 1.0 / (result.matched_n ** 0.5)),
    )
