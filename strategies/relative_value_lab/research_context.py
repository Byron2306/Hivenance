from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ResearchContext:
    schema: str
    context_id: str
    world_state_id: str
    world_state_hash: str
    as_of_ms: int
    observed: Mapping[str, Any]
    regime: Mapping[str, Any]
    statistics: Mapping[str, Any]
    learning: Mapping[str, Any]
    crystals: Mapping[str, Any]
    external: Mapping[str, Any]
    calibration: Mapping[str, Any]
    workers: Mapping[str, Any]
    provenance: Mapping[str, Any]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if not self.world_state_id or not str(self.world_state_hash).startswith("sha256:"):
            raise ValueError("research_context_world_unbound")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("research_context_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "observed", "regime", "statistics", "learning",
            "crystals", "external", "calibration", "workers", "provenance",
        ):
            payload[key] = dict(payload[key])
        return payload


def build_research_context(
    *,
    world_state_id: str,
    world_state_hash: str,
    as_of_ms: int,
    feature_values: Mapping[str, Any] | None = None,
    synthesis_context: Mapping[str, Any] | None = None,
    statistical_state: Mapping[str, Any] | None = None,
    regime_state: Mapping[str, Any] | None = None,
    calibration_state: Mapping[str, Any] | None = None,
    external_features: Sequence[Mapping[str, Any]] = (),
) -> ResearchContext:
    values = dict(feature_values or {})
    synthesis = dict(synthesis_context or {})
    statistical = dict(statistical_state or {})
    regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), Mapping) else {}
    regime = {
        "deterministic": dict(regime_inputs),
        "bayesian": dict(regime_state or {}),
    }

    learning = values.get("phase2_learning_feedback")
    if not isinstance(learning, Mapping):
        learning = synthesis.get("learning") if isinstance(synthesis.get("learning"), Mapping) else {}

    crystals = values.get("phase2_crystal_memory")
    if not isinstance(crystals, Mapping):
        crystals = {}

    workers = {
        "series": dict(values.get("worker_series") or {}) if isinstance(values.get("worker_series"), Mapping) else {},
        "coalition": dict(values.get("worker_coalition") or {}) if isinstance(values.get("worker_coalition"), Mapping) else {},
    }

    external = {
        "features": tuple(dict(x) for x in external_features),
    }

    observed = {
        "cohort_bucket": values.get("cohort_bucket"),
        "tradable_opportunity_score": values.get("tradable_opportunity_score"),
        "research_richness_score": values.get("research_richness_score"),
        "feature_version": values.get("feature_version"),
    }

    provenance = {
        "synthesis_cycle_id": synthesis.get("cycle_id"),
        "statistical_state_id": statistical.get("state_id"),
        "regime_posterior_id": (regime_state or {}).get("posterior_id") if isinstance(regime_state, Mapping) else None,
        "calibration_health_id": (calibration_state or {}).get("health_id") if isinstance(calibration_state, Mapping) else None,
    }

    body = {
        "world_state_id": str(world_state_id),
        "world_state_hash": str(world_state_hash),
        "as_of_ms": int(as_of_ms),
        "observed": observed,
        "regime": regime,
        "statistics": statistical,
        "learning": dict(learning),
        "crystals": dict(crystals),
        "external": external,
        "calibration": dict(calibration_state or {}),
        "workers": workers,
        "provenance": provenance,
    }

    return ResearchContext(
        schema="hivenance_research_context_v1",
        context_id="rctx_" + _digest(body).split(":", 1)[1][:24],
        world_state_id=str(world_state_id),
        world_state_hash=str(world_state_hash),
        as_of_ms=int(as_of_ms),
        observed=observed,
        regime=regime,
        statistics=statistical,
        learning=dict(learning),
        crystals=dict(crystals),
        external=external,
        calibration=dict(calibration_state or {}),
        workers=workers,
        provenance=provenance,
    )


def bind_research_context_values(
    values: Mapping[str, Any] | None,
    context: ResearchContext,
) -> dict[str, Any]:
    out = dict(values or {})
    out["research_context"] = context.to_dict()

    # Compatibility aliases remain until replay ablations prove they can go.
    if context.regime.get("deterministic"):
        out.setdefault("regime_inputs", dict(context.regime["deterministic"]))
    if context.learning:
        out.setdefault("phase2_learning_feedback", dict(context.learning))
    if context.crystals:
        out.setdefault("phase2_crystal_memory", dict(context.crystals))
    if context.statistics:
        out.setdefault("phase2_statistical_hypothesis_context", {
            "schema": "hivenance_hypothesis_statistical_context_v1",
            "state_id": context.statistics.get("state_id"),
            "as_of_ms": context.statistics.get("as_of_ms"),
            "win_probability": context.statistics.get("hierarchical_win_probability", 0.5),
            "edge_positive_probability": context.statistics.get("hierarchical_edge_positive_probability"),
            "uncertainty": context.statistics.get("uncertainty", 0.0),
            "change_point_probability": context.statistics.get("change_point_probability", 0.0),
            "effective_sample_size": context.statistics.get("effective_sample_size", 0.0),
            "authority": "RESEARCH_CONTEXT_ONLY",
            "execution_eligible": False,
            "promotion_eligible": False,
        })
    return out
