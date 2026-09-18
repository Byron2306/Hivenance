from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Iterable

from .cost_model import ResearchCostModel
from .hypothesis_models import (
    BreakoutContinuationModel,
    DerivativesTrendModel,
    DeterministicRandomBaseline,
    ExhaustionMeanReversionModel,
    MediumHorizonTrendModel,
    NoTradeBaseline,
    SimpleMeanReversionBaseline,
    SimpleMomentumBaseline,
)
from .models import FeatureVector, Forecast
from .research_model_federation import ResearchModelFederation
from .worker_coalition_model import WorkerCoalitionMetaModel
from .worker_signal_federation import WorkerSignalFederation
from .venue_profiles import venue_profile


def _cfg_float(cfg: Any, key: str, default: float) -> float:
    """Read a numeric config attribute without discarding a legitimate 0.0."""
    raw = getattr(cfg, key, default)
    return float(default if raw is None else raw)


def _cfg_int(cfg: Any, key: str, default: int) -> int:
    raw = getattr(cfg, key, default)
    return int(default if raw is None else raw)


class HypothesisCompetition:
    """Runs frozen Phase-2 hypotheses and baselines on the same feature vector."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        venue = str(getattr(cfg, "exchange", "kraken") or "kraken").lower()
        economics = venue_profile(venue, cfg)
        cost_model = ResearchCostModel(
            # Phase 2 must clear the same account-tier fee hurdle used by Phase 3.
            # For non-kraken (e.g. dex_*) venues, venue_profile() already zeroes
            # the CEX taker-fee term below since on-chain trades have no exchange
            # fee schedule -- AMM/gas friction is priced through spread/depth
            # instead (see DexPublicClient.fetch_order_book).
            taker_fee_bps_per_side=economics.taker_fee_bps,
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
        self.worker_federation = WorkerSignalFederation(cfg, cost_model)
        self.worker_coalition_models = (
            (WorkerCoalitionMetaModel(cfg, cost_model),)
            if bool(getattr(cfg, "phase2_worker_coalition_enabled", True))
            else ()
        )
        self.medium_trend_models = (
            (
                MediumHorizonTrendModel(
                    cost_model,
                    min_data_quality=float(getattr(cfg, "medium_trend_min_data_quality", 0.99) or 0.99),
                    min_momentum_bps=float(getattr(cfg, "medium_trend_min_momentum_bps", 35.0) or 35.0),
                    min_lower_bound_net_bps=float(getattr(cfg, "medium_trend_min_lower_bound_net_bps", 5.0) or 5.0),
                    min_receipt_entries=int(getattr(cfg, "medium_trend_min_entries_per_slice", 8) or 8),
                    maker_fee_bps_per_side=economics.maker_fee_bps,
                    slippage_bps=float(getattr(cfg, "medium_trend_slippage_bps", 10.0) or 10.0),
                ),
            )
            if bool(getattr(cfg, "medium_trend_phase2_model_enabled", True))
            else ()
        )
        self.derivatives_trend_models = (
            (
                DerivativesTrendModel(
                    cost_model,
                    min_data_quality=_cfg_float(cfg, "derivatives_trend_min_data_quality", 0.99),
                    min_momentum_bps=_cfg_float(cfg, "derivatives_trend_min_momentum_bps", 25.0),
                    min_lower_bound_net_bps=_cfg_float(cfg, "derivatives_trend_min_lower_bound_net_bps", 10.0),
                    min_receipt_entries=_cfg_int(cfg, "derivatives_trend_min_entries_per_slice", 8),
                    maker_fee_bps_per_side=_cfg_float(cfg, "derivatives_trend_maker_fee_bps", 2.0),
                    taker_fee_bps_per_side=_cfg_float(cfg, "derivatives_trend_taker_fee_bps", 5.0),
                    slippage_bps=_cfg_float(cfg, "derivatives_trend_slippage_bps", 3.0),
                    post_only_fill_probability=_cfg_float(cfg, "derivatives_trend_post_only_fill_probability", 0.75),
                ),
            )
            if bool(getattr(cfg, "derivatives_trend_phase2_model_enabled", True))
            else ()
        )
        self.derivatives_trend_ml_veto_enabled = bool(getattr(cfg, "derivatives_trend_ml_veto_enabled", True))
        self.derivatives_trend_ml_veto_max_failure_probability = float(
            getattr(cfg, "derivatives_trend_ml_veto_max_failure_probability", 0.50) or 0.50
        )
        self.worker_models = (*self.worker_federation.models, *self.worker_coalition_models)
        self._all_nonbaseline_models = {
            model.model_id: model
            for model in (
                *self.primary_models,
                *self.federated_models,
                *self.worker_models,
                *self.medium_trend_models,
                *self.derivatives_trend_models,
            )
        }
        self._cohort_preferences = {
            "core_liquid": None,
            "event_driven": {
                "breakout_continuation_v1",
                "adapter_freqtrade_breakout_v1",
                "adapter_jesse_trend_pullback_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
                "candidate_cex_multi_horizon_oracle_v1",
                "candidate_triune_polyphonic_synthesis_v1",
                "worker_signal_breakout_v1",
                "worker_signal_momentum_v1",
                "worker_signal_supertrend_v1",
                "worker_signal_vol_expansion_v1",
                "worker_signal_sma_v1",
                "worker_coalition_meta_v1",
            },
            "mean_reversion": {
                "exhaustion_mean_reversion_v1",
                "adapter_jesse_trend_pullback_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
                "candidate_cex_multi_horizon_oracle_v1",
                "candidate_triune_polyphonic_synthesis_v1",
                "worker_signal_rsi_v1",
                "worker_signal_rsi2_v1",
                "worker_signal_bollinger_v1",
                "worker_signal_supertrend_v1",
                "worker_coalition_meta_v1",
            },
            "research_bench": {
                "breakout_continuation_v1",
                "exhaustion_mean_reversion_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
                "candidate_cex_multi_horizon_oracle_v1",
                "candidate_triune_polyphonic_synthesis_v1",
                "worker_signal_sma_v1",
                "worker_signal_rsi_v1",
                "worker_signal_rsi2_v1",
                "worker_signal_breakout_v1",
                "worker_signal_momentum_v1",
                "worker_signal_bollinger_v1",
                "worker_signal_supertrend_v1",
                "worker_signal_vol_expansion_v1",
                "worker_coalition_meta_v1",
            },
            "niche_research": {
                "breakout_continuation_v1",
                "exhaustion_mean_reversion_v1",
                "adapter_freqtrade_breakout_v1",
                "adapter_jesse_trend_pullback_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
                "candidate_cex_multi_horizon_oracle_v1",
                "candidate_triune_polyphonic_synthesis_v1",
                "worker_signal_rsi_v1",
                "worker_signal_rsi2_v1",
                "worker_signal_breakout_v1",
                "worker_signal_momentum_v1",
                "worker_signal_bollinger_v1",
                "worker_signal_supertrend_v1",
                "worker_signal_vol_expansion_v1",
                "worker_coalition_meta_v1",
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
        return tuple(model.model_id for model in (*self.federated_models, *self.worker_models))

    @property
    def all_model_ids(self) -> tuple[str, ...]:
        return (*self.primary_ids, *self.federated_ids, *self.baseline_ids)

    def federation_manifest(self) -> dict[str, Any]:
        manifest = self.federation.manifest()
        manifest["worker_signal_federation"] = self.worker_federation.manifest()
        manifest["worker_coalition_meta_model"] = {
            "enabled": bool(self.worker_coalition_models),
            "mode": "triune_governed_worker_vote_aggregation",
            "models": [model.model_id for model in self.worker_coalition_models],
            "authority": "research_forecast_only",
            "execution_wired": False,
            "orders_submitted": 0,
        }
        manifest["medium_horizon_trend_model"] = {
            "enabled": bool(self.medium_trend_models),
            "models": [model.model_id for model in self.medium_trend_models],
            "authority": "research_forecast_only",
            "execution_wired": False,
            "orders_submitted": 0,
        }
        manifest["derivatives_trend_model"] = {
            "enabled": bool(self.derivatives_trend_models),
            "models": [model.model_id for model in self.derivatives_trend_models],
            "authority": "research_forecast_only",
            "execution_wired": False,
            "orders_submitted": 0,
            "ml_coalition_veto_enabled": self.derivatives_trend_ml_veto_enabled,
            "product": "perpetual_future",
            "leverage": 1,
            "price_data_source": "kraken_spot_price_proxy_pending_futures_feed",
        }
        return manifest

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
            chosen = [
                model
                for model in (*self.primary_models, *self.federated_models, *self.worker_models)
                if model.model_id not in suppressed_ids
            ]
            return (*chosen, *self.baseline_models)
        chosen = [
            self._all_nonbaseline_models[model_id]
            for model_id in allowed
            if model_id in self._all_nonbaseline_models and model_id not in suppressed_ids
        ]
        return (*chosen, *self.baseline_models)

    def evaluate_medium_trend(self, features: FeatureVector, horizons: Iterable[int]) -> list[Forecast]:
        forecasts: list[Forecast] = []
        if not self.medium_trend_models:
            return forecasts
        features = self._adaptive_feature(features)
        for horizon in horizons:
            for model in self.medium_trend_models:
                forecast = model.forecast(features, horizon_seconds=int(horizon))
                if forecast.execution_eligible:
                    raise RuntimeError(f"research model {forecast.model_id} attempted execution eligibility")
                forecasts.append(forecast)
        return forecasts

    def evaluate_derivatives_trend(self, features: FeatureVector, horizons: Iterable[int]) -> list[Forecast]:
        """Engine A pipeline: deterministic trend says trade -> ML coalition
        estimates failure probability -> (DIO checks economics/evidence
        automatically once the forecast is persisted) -> execute or abstain.

        The worker coalition is a veto layer here, not the alpha generator:
        it never originates a derivatives-trend forecast on its own, it can
        only downgrade an already-deterministic ``DerivativesTrendModel``
        forecast to an abstain.
        """
        forecasts: list[Forecast] = []
        if not self.derivatives_trend_models:
            return forecasts
        features = self._adaptive_feature(features)
        coalition_model = self.worker_coalition_models[0] if self.worker_coalition_models else None
        for horizon in horizons:
            for model in self.derivatives_trend_models:
                forecast = model.forecast(features, horizon_seconds=int(horizon))
                if forecast.execution_eligible:
                    raise RuntimeError(f"research model {forecast.model_id} attempted execution eligibility")
                if not forecast.abstain and self.derivatives_trend_ml_veto_enabled and coalition_model is not None:
                    coalition_forecast = coalition_model.forecast(features, horizon_seconds=int(horizon))
                    veto_reason = self._derivatives_trend_ml_veto_reason(forecast, coalition_forecast)
                    if veto_reason:
                        inputs = dict(forecast.inputs or {})
                        inputs["ml_coalition_forecast"] = asdict(coalition_forecast)
                        forecast = replace(
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
                forecasts.append(forecast)
        return forecasts

    def _derivatives_trend_ml_veto_reason(self, forecast: Forecast, coalition_forecast: Forecast) -> str | None:
        if coalition_forecast.abstain:
            # The coalition has no opinion; the deterministic model's own
            # statistical/economics gates already govern this trade.
            return None
        if coalition_forecast.direction in ("ABSTAIN",):
            return None
        if coalition_forecast.direction != forecast.direction:
            return "ml_coalition_veto"
        failure_probability = 1.0 - float(coalition_forecast.probability_positive_net or 0.5)
        if failure_probability > self.derivatives_trend_ml_veto_max_failure_probability:
            return "ml_coalition_veto"
        return None

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
        crystal_memory = values.get("phase2_crystal_memory") if isinstance(values.get("phase2_crystal_memory"), dict) else {}
        crystal_support = float(crystal_memory.get("support_score") or 0.0)
        crystal_warning = float(crystal_memory.get("warning_score") or 0.0)
        crystal_positive_bias = max(0.0, min(1.0, crystal_support * 0.15))
        crystal_warning_drag = max(0.0, min(1.0, crystal_warning * 0.15))
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
            and regime_confidence >= max(0.45, 0.60 - crystal_positive_bias + crystal_warning_drag)
            and tradable_score >= max(0.45, 0.60 - crystal_positive_bias + crystal_warning_drag)
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
                "adaptation_reason": "event_driven_high_tradable_opportunity_with_crystal_bias" if crystal_positive_bias > 0 else "event_driven_high_tradable_opportunity",
                "crystal_support_score": round(crystal_support, 6),
                "crystal_warning_score": round(crystal_warning, 6),
            }
        if (
            cohort in {"mean_reversion", "research_bench"}
            and regime_hint in {"stretch_exhaustion", "quiet_range", "balanced_transition"}
            and regime_confidence >= max(0.45, 0.58 - crystal_positive_bias + crystal_warning_drag)
            and max(tradable_score, research_score) >= max(0.45, 0.58 - crystal_positive_bias + crystal_warning_drag)
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
                "adaptation_reason": "mean_reversion_high_research_value_with_crystal_bias" if crystal_positive_bias > 0 else "mean_reversion_high_research_value",
                "crystal_support_score": round(crystal_support, 6),
                "crystal_warning_score": round(crystal_warning, 6),
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
