from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Iterable

from .cost_model import ResearchCostModel
from .hypothesis_models import (
    BreakoutContinuationModel,
    DeterministicRandomBaseline,
    ExhaustionMeanReversionModel,
    NoTradeBaseline,
    SimpleMeanReversionBaseline,
    SimpleMomentumBaseline,
)
from .models import FeatureVector, Forecast
from .research_model_federation import ResearchModelFederation


class HypothesisCompetition:
    """Runs frozen Phase-2 hypotheses and baselines on the same feature vector."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        cost_model = ResearchCostModel(
            taker_fee_bps_per_side=float(getattr(cfg, "phase2_taker_fee_bps_per_side", 10.0) or 10.0),
            reference_notional_usd=float(getattr(cfg, "phase2_reference_notional_usd", 5.0) or 5.0),
            latency_buffer_bps=float(getattr(cfg, "phase2_latency_buffer_bps", 2.0) or 2.0),
            safety_buffer_bps=float(getattr(cfg, "phase2_safety_buffer_bps", 3.0) or 3.0),
            max_total_cost_bps=float(getattr(cfg, "phase2_max_total_cost_bps", 150.0) or 150.0),
        )
        min_quality = float(getattr(cfg, "phase2_min_data_quality", 0.99) or 0.99)
        edge_multiple = float(getattr(cfg, "phase2_minimum_edge_multiple", 2.0) or 2.0)
        self.primary_models = (
            BreakoutContinuationModel(
                cost_model,
                min_data_quality=min_quality,
                min_expansion=float(getattr(cfg, "phase2_breakout_min_expansion", 1.25) or 1.25),
                min_volume_zscore=float(getattr(cfg, "phase2_breakout_min_volume_zscore", 0.50) or 0.50),
                min_return_zscore=float(getattr(cfg, "phase2_breakout_min_return_zscore", 0.75) or 0.75),
                minimum_edge_multiple=edge_multiple,
                allowed_regimes=tuple(
                    getattr(cfg, "phase2_breakout_allowed_regimes", ("trend_expansion", "balanced_transition"))
                    or ("trend_expansion", "balanced_transition")
                ),
                min_regime_confidence=float(getattr(cfg, "phase2_breakout_min_regime_confidence", 0.35) or 0.35),
                min_tradability_score=float(getattr(cfg, "phase2_breakout_min_tradability_score", 0.55) or 0.55),
                min_momentum_consistency=float(getattr(cfg, "phase2_breakout_min_momentum_consistency", 0.55) or 0.55),
            ),
            ExhaustionMeanReversionModel(
                cost_model,
                min_data_quality=min_quality,
                min_stretch_zscore=float(getattr(cfg, "phase2_reversion_min_stretch_zscore", 1.50) or 1.50),
                min_range_extreme=float(getattr(cfg, "phase2_reversion_min_range_extreme", 0.85) or 0.85),
                minimum_edge_multiple=edge_multiple,
                allowed_regimes=tuple(
                    getattr(cfg, "phase2_reversion_allowed_regimes", ("stretch_exhaustion", "quiet_range", "balanced_transition"))
                    or ("stretch_exhaustion", "quiet_range", "balanced_transition")
                ),
                min_regime_confidence=float(getattr(cfg, "phase2_reversion_min_regime_confidence", 0.30) or 0.30),
                min_tradability_score=float(getattr(cfg, "phase2_reversion_min_tradability_score", 0.50) or 0.50),
                min_reversal_strength=float(getattr(cfg, "phase2_reversion_min_reversal_strength", 0.30) or 0.30),
            ),
        )
        self.baseline_models = (
            NoTradeBaseline(),
            SimpleMomentumBaseline(cost_model),
            SimpleMeanReversionBaseline(cost_model),
            DeterministicRandomBaseline(cost_model),
        )
        self.federation = ResearchModelFederation(cfg, cost_model)
        self.federated_models = self.federation.models
        self._all_nonbaseline_models = {model.model_id: model for model in (*self.primary_models, *self.federated_models)}
        self._cohort_preferences = {
            "core_liquid": None,
            "event_driven": {
                "breakout_continuation_v1",
                "adapter_freqtrade_breakout_v1",
                "adapter_jesse_trend_pullback_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
            },
            "mean_reversion": {
                "exhaustion_mean_reversion_v1",
                "adapter_jesse_trend_pullback_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
            },
            "research_bench": {
                "breakout_continuation_v1",
                "exhaustion_mean_reversion_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
            },
        }
        self.require_frontier_for_adaptive_recovery = bool(
            getattr(cfg, "phase2_require_frontier_for_adaptive_recovery", True)
        )
        self.frontier_min_realized_net_bps = float(
            getattr(cfg, "phase2_frontier_min_realized_net_bps", 2.5) or 2.5
        )
        self.frontier_min_samples = max(
            1,
            int(getattr(cfg, "phase2_frontier_min_samples", 5) or 5),
        )

    @property
    def primary_ids(self) -> tuple[str, ...]:
        return tuple(model.model_id for model in self.primary_models)

    @property
    def baseline_ids(self) -> tuple[str, ...]:
        return tuple(model.model_id for model in self.baseline_models)

    @property
    def federated_ids(self) -> tuple[str, ...]:
        return tuple(model.model_id for model in self.federated_models)

    @property
    def all_model_ids(self) -> tuple[str, ...]:
        return (*self.primary_ids, *self.federated_ids, *self.baseline_ids)

    def federation_manifest(self) -> dict[str, Any]:
        return self.federation.manifest()

    @staticmethod
    def _cohort_bucket(features: FeatureVector) -> str:
        values = features.values if isinstance(features.values, dict) else {}
        return str(values.get("cohort_bucket") or "unknown")

    def _active_models_for(self, features: FeatureVector) -> tuple[Any, ...]:
        cohort = self._cohort_bucket(features)
        allowed = self._cohort_preferences.get(cohort)
        values = features.values if isinstance(features.values, dict) else {}
        regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
        regime_hint = str(regime_inputs.get("regime_hint") or "unknown")
        suppression = values.get("phase2_regime_suppression") if isinstance(values.get("phase2_regime_suppression"), dict) else {}
        suppressed = suppression.get(regime_hint) if isinstance(suppression.get(regime_hint), dict) else {}
        suppressed_ids = {
            str(model_id)
            for model_id, payload in suppressed.items()
            if isinstance(payload, dict) and bool(payload.get("suppressed"))
        }
        if not allowed:
            chosen = [model for model in (*self.primary_models, *self.federated_models) if model.model_id not in suppressed_ids]
            return (*chosen, *self.baseline_models)
        chosen = [
            self._all_nonbaseline_models[model_id]
            for model_id in allowed
            if model_id in self._all_nonbaseline_models and model_id not in suppressed_ids
        ]
        return (*chosen, *self.baseline_models)

    def _adaptive_feature(self, features: FeatureVector) -> FeatureVector:
        values = dict(features.values or {})
        cohort = str(values.get("cohort_bucket") or "unknown")
        tradable_score = float(values.get("tradable_opportunity_score") or 0.0)
        research_score = float(values.get("research_richness_score") or 0.0)
        regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
        regime_hint = str(regime_inputs.get("regime_hint") or "unknown")
        regime_confidence = float(regime_inputs.get("confidence") or 0.0)
        breakout_borderline = (
            float(features.volatility_expansion or 0.0) >= max(1.0, float(getattr(self.primary_models[0], "min_expansion", 1.25)) * 0.88)
            and float(features.volume_zscore or -99.0) >= float(getattr(self.primary_models[0], "min_volume_zscore", 0.50)) * 0.60
            and abs(float(features.return_zscore or 0.0)) >= float(getattr(self.primary_models[0], "min_return_zscore", 0.75)) * 0.70
        )
        reversion_borderline = (
            abs(float((features.return_zscore if features.return_zscore is not None else features.price_zscore) or 0.0))
            >= float(getattr(self.primary_models[1], "min_stretch_zscore", 1.50)) * 0.75
            and abs(float(features.range_position or 0.5) - 0.5) * 2.0
            >= float(getattr(self.primary_models[1], "min_range_extreme", 0.85)) * 0.75
        )
        frontier_map = values.get("phase2_profitability_frontier") if isinstance(values.get("phase2_profitability_frontier"), dict) else {}
        breakout_frontier = frontier_map.get("breakout") if isinstance(frontier_map.get("breakout"), dict) else {}
        reversion_frontier = frontier_map.get("reversion") if isinstance(frontier_map.get("reversion"), dict) else {}
        breakout_frontier_ok = (
            not self.require_frontier_for_adaptive_recovery
            or (
                bool(breakout_frontier.get("eligible"))
                and float(breakout_frontier.get("mean_realized_net_bps") or 0.0) >= self.frontier_min_realized_net_bps
                and int(breakout_frontier.get("settled_trades") or 0) >= self.frontier_min_samples
            )
        )
        reversion_frontier_ok = (
            not self.require_frontier_for_adaptive_recovery
            or (
                bool(reversion_frontier.get("eligible"))
                and float(reversion_frontier.get("mean_realized_net_bps") or 0.0) >= self.frontier_min_realized_net_bps
                and int(reversion_frontier.get("settled_trades") or 0) >= self.frontier_min_samples
            )
        )
        policy: dict[str, dict[str, float | bool | str]] = {}
        if (
            cohort == "event_driven"
            and regime_hint in {"trend_expansion", "balanced_transition"}
            and regime_confidence >= 0.60
            and tradable_score >= 0.60
            and breakout_borderline
            and breakout_frontier_ok
        ):
            policy["breakout"] = {
                "min_expansion": round(float(getattr(self.primary_models[0], "min_expansion", 1.25)) * 0.92, 6),
                "min_return_zscore": round(float(getattr(self.primary_models[0], "min_return_zscore", 0.75)) * 0.90, 6),
                "min_momentum_consistency": round(float(getattr(self.primary_models[0], "min_momentum_consistency", 0.55)) * 0.94, 6),
                "minimum_edge_multiple": round(float(getattr(self.primary_models[0], "minimum_edge_multiple", 2.0)) * 0.90, 6),
                "recovery_mode": "borderline_regime_confirmed",
                "adaptation_strength": round(min(1.0, 0.55 * tradable_score + 0.45 * regime_confidence), 6),
                "frontier_context": breakout_frontier,
                "adaptation_reason": "event_driven_high_tradable_opportunity",
            }
        if (
            cohort in {"mean_reversion", "research_bench"}
            and regime_hint in {"stretch_exhaustion", "quiet_range", "balanced_transition"}
            and regime_confidence >= 0.58
            and max(tradable_score, research_score) >= 0.58
            and reversion_borderline
            and reversion_frontier_ok
        ):
            policy["reversion"] = {
                "min_stretch_zscore": round(float(getattr(self.primary_models[1], "min_stretch_zscore", 1.50)) * 0.88, 6),
                "min_range_extreme": round(max(0.78, float(getattr(self.primary_models[1], "min_range_extreme", 0.85)) * 0.96), 6),
                "min_reversal_strength": round(float(getattr(self.primary_models[1], "min_reversal_strength", 0.30)) * 0.92, 6),
                "minimum_edge_multiple": round(float(getattr(self.primary_models[1], "minimum_edge_multiple", 2.0)) * 0.90, 6),
                "recovery_mode": "borderline_regime_confirmed",
                "adaptation_strength": round(min(1.0, 0.45 * tradable_score + 0.55 * max(research_score, regime_confidence)), 6),
                "frontier_context": reversion_frontier,
                "adaptation_reason": "mean_reversion_high_research_value",
            }
        if not policy:
            return features
        values["phase2_adaptive_thresholds"] = policy
        return replace(features, values=values)

    def evaluate(self, features: FeatureVector, horizons: Iterable[int]) -> list[Forecast]:
        forecasts: list[Forecast] = []
        features = self._adaptive_feature(features)
        active_models = self._active_models_for(features)
        for horizon in horizons:
            for model in active_models:
                forecast = model.forecast(features, horizon_seconds=int(horizon))
                if forecast.execution_eligible:
                    raise RuntimeError(f"research model {forecast.model_id} attempted execution eligibility")
                forecasts.append(forecast)
        return forecasts

    @staticmethod
    def summarize(forecasts: Iterable[Forecast]) -> dict[str, Any]:
        rows = list(forecasts)
        return {
            "forecasts_total": len(rows),
            "non_abstain_forecasts": sum(1 for item in rows if not item.abstain),
            "abstentions": sum(1 for item in rows if item.abstain),
            "by_model": {
                model_id: {
                    "forecasts": sum(1 for item in rows if item.model_id == model_id),
                    "non_abstain": sum(1 for item in rows if item.model_id == model_id and not item.abstain),
                }
                for model_id in sorted({item.model_id for item in rows})
            },
        }
