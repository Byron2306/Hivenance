from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping

from strategies.volatility_breakout.models import FeatureVector, Forecast


@dataclass(frozen=True)
class HypothesisStatisticalContext:
    schema: str
    state_id: str
    as_of_ms: int
    win_probability: float
    edge_positive_probability: float | None
    uncertainty: float
    change_point_probability: float
    effective_sample_size: float
    authority: str = "RESEARCH_CONTEXT_ONLY"
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def context_from_synthesis_state(state: Any) -> HypothesisStatisticalContext:
    payload = state.to_dict() if hasattr(state, "to_dict") else dict(state)
    return HypothesisStatisticalContext(
        schema="hivenance_hypothesis_statistical_context_v1",
        state_id=str(payload.get("state_id") or ""),
        as_of_ms=int(payload.get("as_of_ms") or 0),
        win_probability=float(payload.get("hierarchical_win_probability") or 0.5),
        edge_positive_probability=(
            None if payload.get("hierarchical_edge_positive_probability") is None
            else float(payload.get("hierarchical_edge_positive_probability"))
        ),
        uncertainty=float(payload.get("uncertainty") or 0.0),
        change_point_probability=float(payload.get("change_point_probability") or 0.0),
        effective_sample_size=float(payload.get("effective_sample_size") or 0.0),
    )


def bind_statistical_context(
    feature: FeatureVector,
    state: Any,
) -> FeatureVector:
    context = context_from_synthesis_state(state)
    if context.as_of_ms > int(feature.timestamp_ms):
        raise ValueError("hypothesis_statistical_context_from_future")
    values = dict(feature.values or {})
    values["phase2_statistical_hypothesis_context"] = context.to_dict()
    return replace(feature, values=values)


def bind_statistical_contexts(
    feature: FeatureVector,
    states_by_model: Mapping[str, Any],
) -> FeatureVector:
    values = dict(feature.values or {})
    bound = {}
    for model_id, state in states_by_model.items():
        context = context_from_synthesis_state(state)
        if context.as_of_ms > int(feature.timestamp_ms):
            raise ValueError("hypothesis_statistical_context_from_future")
        bound[str(model_id)] = context.to_dict()
    values["phase2_statistical_hypothesis_context_by_model"] = bound
    return replace(feature, values=values)


def statistical_hypothesis_gate(
    forecast: Forecast,
    feature: FeatureVector,
    *,
    min_effective_samples: float = 5.0,
    max_uncertainty: float = 0.82,
    max_change_point_probability: float = 0.78,
    min_edge_positive_probability: float = 0.35,
) -> Forecast:
    """Conservative hypothesis gate.

    Statistics may annotate or veto an existing research forecast. They may not
    create direction, flip direction, manufacture edge, or grant authority.
    Positive statistical evidence is therefore observational until prospective
    causal tests explicitly promote stronger influence.
    """
    values = feature.values if isinstance(feature.values, Mapping) else {}
    raw = None
    by_model = values.get("phase2_statistical_hypothesis_context_by_model")
    if isinstance(by_model, Mapping):
        candidate = by_model.get(str(forecast.model_id))
        if isinstance(candidate, Mapping):
            raw = candidate
    if raw is None:
        candidate = values.get("phase2_statistical_hypothesis_context")
        if isinstance(candidate, Mapping):
            raw = candidate
    if not isinstance(raw, Mapping):
        return forecast

    inputs = dict(forecast.inputs or {})
    inputs["statistical_hypothesis_context"] = dict(raw)

    if forecast.abstain:
        return replace(forecast, inputs=inputs, execution_eligible=False)

    uncertainty = float(raw.get("uncertainty") or 0.0)
    change = float(raw.get("change_point_probability") or 0.0)
    n_eff = float(raw.get("effective_sample_size") or 0.0)
    edge_p = raw.get("edge_positive_probability")

    veto_reason = None
    if uncertainty >= float(max_uncertainty):
        veto_reason = "statistical_synthesis_uncertainty_veto"
    elif change >= float(max_change_point_probability):
        veto_reason = "statistical_synthesis_change_point_veto"
    elif (
        edge_p is not None
        and n_eff >= float(min_effective_samples)
        and float(edge_p) <= float(min_edge_positive_probability)
    ):
        veto_reason = "statistical_synthesis_negative_edge_veto"

    if veto_reason is None:
        return replace(forecast, inputs=inputs, execution_eligible=False)

    return replace(
        forecast,
        direction="ABSTAIN",
        probability_positive_net=None,
        expected_move_bps=None,
        expected_net_bps=None,
        abstain=True,
        reason=veto_reason,
        reasons=(*forecast.reasons, veto_reason),
        inputs=inputs,
        execution_eligible=False,
    )
