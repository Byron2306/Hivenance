from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from .cost_model import CostEstimate, ResearchCostModel
from .advanced_systems_synthesis import AdvancedSystemsMarketSynthesizer
from .models import FeatureVector, Forecast


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _signed(value: float | None) -> int:
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def _direction(sign: int) -> str:
    return "UP" if sign > 0 else "DOWN" if sign < 0 else "ABSTAIN"


def _horizon_scale(horizon_seconds: int, *, cap: float = 2.75) -> float:
    return max(0.75, min(float(cap), math.sqrt(max(60, int(horizon_seconds)) / 300.0)))


def _tanh(value: float | None, scale: float = 1.0) -> float:
    if value is None:
        return 0.0
    return math.tanh(float(value) * scale)


def _logistic_probability(magnitude: float, *, ceiling: float = 0.80) -> float:
    confidence = 1.0 / (1.0 + math.exp(-2.2 * max(0.0, float(magnitude))))
    return round(0.50 + (ceiling - 0.50) * _clip((confidence - 0.5) * 2.0), 6)


def _signal_move_proxy_bps(
    features: FeatureVector,
    *,
    directional_score: float,
    horizon_seconds: int,
) -> float:
    horizon = _horizon_scale(horizon_seconds, cap=2.2)
    signal = abs(float(directional_score or 0.0))
    recent_return_bps = abs(float(features.return_5 or 0.0)) * 10_000.0
    zscore_impulse_bps = abs(float(features.return_zscore or 0.0)) * 16.0
    trend_impulse_bps = abs(float(features.trend_slope or 0.0)) * 140_000.0
    book_impulse_bps = abs(float(features.book_imbalance or 0.0)) * 10.0
    volume_bonus_bps = max(0.0, float(features.volume_zscore or 0.0)) * 3.5
    range_bonus_bps = abs(float(features.range_position or 0.5) - 0.5) * 10.0
    return horizon * (
        0.55 * recent_return_bps
        + 0.25 * zscore_impulse_bps
        + 0.10 * trend_impulse_bps
        + 0.05 * book_impulse_bps
        + 0.03 * volume_bonus_bps
        + 0.02 * range_bonus_bps
    ) * (0.70 + 0.45 * _clip(signal, 0.0, 1.5))


@dataclass(frozen=True)
class FederatedModelDescriptor:
    model_id: str
    family: str
    role: str
    implementation: str
    fidelity: str
    external_runtime: bool
    training_mode: str
    authority: str = "research_forecast_only"
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FederatedResearchModel:
    model_id = "federated_model"
    hypothesis = "federated_research"
    is_baseline = False
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="unknown",
        role="FEDERATED",
        implementation="internal",
        fidelity="TRANSPARENT_PROXY",
        external_runtime=False,
        training_mode="frozen_rules",
    )

    def __init__(
        self,
        cost_model: ResearchCostModel,
        *,
        min_data_quality: float = 0.99,
        minimum_edge_multiple: float = 1.25,
        score_scale: float = 1.0,
    ) -> None:
        self.cost_model = cost_model
        self.min_data_quality = float(min_data_quality)
        self.minimum_edge_multiple = max(1.0, float(minimum_edge_multiple))
        self.score_scale = max(0.5, float(score_scale))

    def _base_reasons(self, features: FeatureVector, cost: CostEstimate) -> list[str]:
        reasons: list[str] = []
        if not features.complete:
            reasons.append("features_incomplete")
        if float(features.data_quality or 0.0) < self.min_data_quality:
            reasons.append("data_quality_below_gate")
        if not cost.tradable:
            reasons.append(cost.reason)
        return reasons

    def _inputs(self, features: FeatureVector, cost: CostEstimate) -> dict[str, Any]:
        return {
            "federation": self.descriptor.to_dict(),
            "feature_version": (features.values or {}).get("feature_version", "phase2.v1"),
            "cohort_bucket": (features.values or {}).get("cohort_bucket", "unknown"),
            "return_5": features.return_5,
            "return_zscore": features.return_zscore,
            "price_zscore": features.price_zscore,
            "range_position": features.range_position,
            "trend_slope": features.trend_slope,
            "atr_pct": features.atr_pct,
            "volatility_expansion": features.volatility_expansion,
            "volume_zscore": features.volume_zscore,
            "volume_ratio": features.volume_ratio,
            "momentum_consistency": features.momentum_consistency,
            "reversal_return_1": features.reversal_return_1,
            "book_imbalance": features.book_imbalance,
            "spread_bps": features.spread_bps,
            "depth_usd_25bps": features.depth_usd_25bps,
            "cost": asdict(cost),
        }

    def _abstain(
        self,
        features: FeatureVector,
        horizon_seconds: int,
        reasons: Iterable[str],
        *,
        cost: CostEstimate,
        raw_score: float | None = None,
        inputs: Mapping[str, Any] | None = None,
    ) -> Forecast:
        reason_list = tuple(str(item) for item in reasons if item)
        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=int(horizon_seconds),
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            direction="ABSTAIN",
            probability_positive_net=None,
            expected_move_bps=None,
            expected_cost_bps=cost.total_bps,
            expected_net_bps=None,
            raw_score=None if raw_score is None else round(float(raw_score), 6),
            uncertainty=1.0,
            calibration_state="FEDERATED_COLD_START",
            feature_version="phase7.2.federation.v1",
            abstain=True,
            reason=reason_list[0] if reason_list else "federated_abstain",
            reasons=reason_list,
            inputs=dict(inputs or self._inputs(features, cost)),
            execution_eligible=False,
        )

    def _emit(
        self,
        features: FeatureVector,
        horizon_seconds: int,
        *,
        sign: int,
        score: float,
        expected_move_bps: float,
        cost: CostEstimate,
        reason: str,
        inputs: Mapping[str, Any] | None = None,
        probability_ceiling: float = 0.80,
    ) -> Forecast:
        edge_multiple = float(expected_move_bps) / max(float(cost.total_bps), 0.000001)
        expected_net = float(expected_move_bps) - float(cost.total_bps)
        merged_inputs = dict(inputs or self._inputs(features, cost))
        merged_inputs.update({
            "horizon_scale": round(_horizon_scale(horizon_seconds), 6),
            "edge_multiple": round(edge_multiple, 6),
            "federation": self.descriptor.to_dict(),
        })
        if sign == 0:
            return self._abstain(features, horizon_seconds, ["direction_unavailable"], cost=cost, raw_score=score, inputs=merged_inputs)
        if expected_net <= 0 or edge_multiple < self.minimum_edge_multiple:
            return self._abstain(
                features,
                horizon_seconds,
                ["insufficient_cost_adjusted_edge"],
                cost=cost,
                raw_score=score,
                inputs=merged_inputs,
            )
        magnitude = _clip(abs(float(score)), 0.0, 1.5)
        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=int(horizon_seconds),
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            direction=_direction(sign),
            probability_positive_net=_logistic_probability(magnitude, ceiling=probability_ceiling),
            expected_move_bps=round(float(expected_move_bps), 6),
            expected_cost_bps=round(float(cost.total_bps), 6),
            expected_net_bps=round(expected_net, 6),
            raw_score=round(float(score), 6),
            uncertainty=round(1.0 - _clip(magnitude), 6),
            calibration_state="FEDERATED_COLD_START_PROVISIONAL",
            feature_version="phase7.2.federation.v1",
            abstain=False,
            reason=reason,
            reasons=(),
            inputs=merged_inputs,
            execution_eligible=False,
        )


class FreqtradeBreakoutAdapter(FederatedResearchModel):
    model_id = "adapter_freqtrade_breakout_v1"
    hypothesis = "freqtrade_style_multifactor_breakout"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="freqtrade",
        role="FEDERATED",
        implementation="internal_deterministic_strategy_adapter",
        fidelity="FRAMEWORK_STYLE_ADAPTER_NOT_FREQTRADE_RUNTIME",
        external_runtime=False,
        training_mode="frozen_rules",
    )

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        sign = _signed(features.return_5)
        trend_sign = _signed(features.trend_slope)
        if sign == 0:
            reasons.append("direction_unavailable")
        if float(features.volatility_expansion or 0.0) < 1.05:
            reasons.append("breakout_regime_absent")
        if float(features.volume_zscore or -9.0) < 0.0:
            reasons.append("volume_confirmation_absent")
        if float(features.momentum_consistency or 0.0) < 0.55:
            reasons.append("momentum_consistency_low")
        if trend_sign and sign and trend_sign != sign:
            reasons.append("trend_not_aligned")
        if features.range_position is None:
            reasons.append("range_position_unavailable")
        elif sign > 0 and features.range_position < 0.62:
            reasons.append("upside_breakout_not_near_range_high")
        elif sign < 0 and features.range_position > 0.38:
            reasons.append("downside_breakout_not_near_range_low")
        inputs = self._inputs(features, cost)
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, inputs=inputs)

        score = (
            0.25 * _clip((float(features.volatility_expansion or 1.0) - 1.0) / 2.0)
            + 0.20 * _clip((float(features.volume_zscore or 0.0) + 0.5) / 3.0)
            + 0.20 * _clip(abs(float(features.return_zscore or 0.0)) / 2.5)
            + 0.15 * _clip(float(features.momentum_consistency or 0.0))
            + 0.10 * (1.0 if not trend_sign or trend_sign == sign else 0.0)
            + 0.10 * _clip(0.5 + 0.5 * float(features.book_imbalance or 0.0) * sign)
        )
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        move = atr_bps * _horizon_scale(horizon_seconds) * (0.52 + 0.78 * score)
        return self._emit(features, horizon_seconds, sign=sign, score=score, expected_move_bps=move, cost=cost,
                          reason="freqtrade_style_breakout_passed", inputs=inputs)


class JesseTrendPullbackAdapter(FederatedResearchModel):
    model_id = "adapter_jesse_trend_pullback_v1"
    hypothesis = "jesse_style_trend_pullback"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="jesse",
        role="FEDERATED",
        implementation="internal_deterministic_strategy_adapter",
        fidelity="FRAMEWORK_STYLE_ADAPTER_NOT_JESSE_RUNTIME",
        external_runtime=False,
        training_mode="frozen_rules",
    )

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        sign = _signed(features.trend_slope)
        if sign == 0 or abs(float(features.trend_slope or 0.0)) < 0.00005:
            reasons.append("trend_unavailable")
        pullback = features.reversal_return_1 is not None and float(features.reversal_return_1) * sign < 0
        not_broken = features.range_position is not None and (
            (sign > 0 and features.range_position >= 0.45) or (sign < 0 and features.range_position <= 0.55)
        )
        if not pullback:
            reasons.append("pullback_not_present")
        if not not_broken:
            reasons.append("trend_structure_not_intact")
        if float(features.momentum_consistency or 0.0) < 0.50:
            reasons.append("trend_consistency_low")
        inputs = self._inputs(features, cost)
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, inputs=inputs)

        trend_strength = _clip(abs(float(features.trend_slope or 0.0)) * 8_000.0)
        pullback_strength = _clip(abs(float(features.reversal_return_1 or 0.0)) * 10_000.0 / 25.0)
        structure = _clip(abs(float(features.range_position or 0.5) - 0.5) * 2.0)
        book_alignment = _clip(0.5 + 0.5 * float(features.book_imbalance or 0.0) * sign)
        score = 0.38 * trend_strength + 0.22 * pullback_strength + 0.18 * structure + 0.12 * book_alignment + 0.10 * _clip(float(features.momentum_consistency or 0.0))
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        move = atr_bps * _horizon_scale(horizon_seconds) * (0.45 + 0.72 * score)
        return self._emit(features, horizon_seconds, sign=sign, score=score, expected_move_bps=move, cost=cost,
                          reason="jesse_style_trend_pullback_passed", inputs=inputs)


class FreqAITransparentLinearCandidate(FederatedResearchModel):
    model_id = "candidate_freqai_transparent_linear_v1"
    hypothesis = "freqai_style_transparent_supervised_proxy"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="freqai",
        role="FEDERATED",
        implementation="frozen_transparent_linear_proxy",
        fidelity="NO_FREQAI_TRAINING_RUNTIME",
        external_runtime=False,
        training_mode="frozen_coefficients_no_online_retraining",
    )

    def __init__(
        self,
        cost_model: ResearchCostModel,
        *,
        min_data_quality: float = 0.99,
        minimum_edge_multiple: float = 1.25,
        score_scale: float = 1.0,
        confidence_floor: float = 0.40,
    ) -> None:
        super().__init__(
            cost_model,
            min_data_quality=min_data_quality,
            minimum_edge_multiple=minimum_edge_multiple,
            score_scale=score_scale,
        )
        self.confidence_floor = max(0.05, float(confidence_floor))

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        raw = self.score_scale * (
            0.72 * _tanh(features.return_zscore, 0.65)
            + 0.48 * _tanh(features.trend_slope, 4_000.0)
            + 0.34 * float(features.book_imbalance or 0.0)
            + 0.24 * _tanh(features.volume_zscore, 0.55)
            + 0.18 * ((float(features.range_position or 0.5) - 0.5) * 2.0)
            + 0.14 * _tanh((float(features.volatility_expansion or 1.0) - 1.0), 0.8)
        )
        sign = _signed(raw)
        if abs(raw) < self.confidence_floor:
            reasons.append("linear_candidate_confidence_low")
        inputs = self._inputs(features, cost)
        inputs["frozen_coefficients"] = {
            "return_zscore": 0.72, "trend_slope": 0.48, "book_imbalance": 0.34,
            "volume_zscore": 0.24, "range_position": 0.18, "volatility_expansion": 0.14,
        }
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, raw_score=raw, inputs=inputs)
        score = _clip(abs(raw) / 1.75)
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        atr_move = atr_bps * _horizon_scale(horizon_seconds) * (0.42 + 0.80 * score)
        signal_move = _signal_move_proxy_bps(features, directional_score=raw, horizon_seconds=horizon_seconds)
        move = max(atr_move, signal_move)
        inputs["move_components_bps"] = {
            "atr_model": round(atr_move, 6),
            "signal_proxy": round(signal_move, 6),
        }
        return self._emit(features, horizon_seconds, sign=sign, score=score, expected_move_bps=move, cost=cost,
                          reason="freqai_transparent_candidate_passed", inputs=inputs, probability_ceiling=0.76)


class FinRLConservativePolicyProxy(FederatedResearchModel):
    model_id = "candidate_finrl_conservative_policy_proxy_v1"
    hypothesis = "finrl_style_risk_adjusted_policy_proxy"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="finrl_crypto",
        role="FEDERATED",
        implementation="deterministic_risk_adjusted_policy_proxy",
        fidelity="NO_RL_TRAINING_OR_POLICY_CHECKPOINT",
        external_runtime=False,
        training_mode="frozen_policy_no_online_learning",
    )

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        directional = self.score_scale * (
            0.45 * _tanh(features.return_zscore, 0.7)
            + 0.32 * _tanh(features.trend_slope, 4_500.0)
            + 0.18 * float(features.book_imbalance or 0.0)
            + 0.10 * _tanh(features.volume_zscore, 0.5)
        )
        volatility_penalty = _clip((float(features.volatility_expansion or 1.0) - 2.0) / 4.0)
        liquidity_penalty = _clip(float(features.spread_bps or 0.0) / 50.0)
        utility = directional * (1.0 - 0.35 * volatility_penalty) * (1.0 - 0.30 * liquidity_penalty)
        sign = _signed(utility)
        if abs(utility) < 0.30:
            reasons.append("policy_utility_below_abstention_threshold")
        inputs = self._inputs(features, cost)
        inputs.update({"directional_utility": directional, "volatility_penalty": volatility_penalty, "liquidity_penalty": liquidity_penalty})
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, raw_score=utility, inputs=inputs)
        score = _clip(abs(utility))
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        atr_move = atr_bps * _horizon_scale(horizon_seconds) * (0.38 + 0.72 * score)
        signal_move = _signal_move_proxy_bps(features, directional_score=utility, horizon_seconds=horizon_seconds)
        move = max(atr_move, signal_move)
        inputs["move_components_bps"] = {
            "atr_model": round(atr_move, 6),
            "signal_proxy": round(signal_move, 6),
        }
        return self._emit(features, horizon_seconds, sign=sign, score=score, expected_move_bps=move, cost=cost,
                          reason="finrl_conservative_policy_proxy_passed", inputs=inputs, probability_ceiling=0.74)


class MacroHFTRegimeMicrostructureProxy(FederatedResearchModel):
    model_id = "candidate_macrohft_regime_microstructure_proxy_v1"
    hypothesis = "macrohft_style_regime_microstructure_proxy"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="macrohft",
        role="FEDERATED",
        implementation="deterministic_regime_microstructure_proxy",
        fidelity="OBSERVATION_BOOK_PROXY_NO_SEQUENCE_L2",
        external_runtime=False,
        training_mode="frozen_rules",
    )

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        if features.book_imbalance is None or abs(float(features.book_imbalance)) < 0.08:
            reasons.append("microstructure_imbalance_weak")
        if features.spread_bps is None or float(features.spread_bps) > 25.0:
            reasons.append("spread_above_microstructure_gate")
        if features.depth_usd_25bps is None or float(features.depth_usd_25bps) < 25_000.0:
            reasons.append("depth_below_microstructure_gate")
        regime = float(features.volatility_expansion or 1.0)
        if regime < 0.75 or regime > 5.0:
            reasons.append("regime_outside_proxy_envelope")
        raw = (
            0.58 * float(features.book_imbalance or 0.0)
            + 0.22 * _tanh(features.return_zscore, 0.65)
            + 0.14 * _tanh(features.trend_slope, 4_000.0)
            + 0.06 * _tanh(features.volume_zscore, 0.5)
        )
        sign = _signed(raw)
        if abs(raw) < 0.12:
            reasons.append("microstructure_consensus_low")
        inputs = self._inputs(features, cost)
        inputs["book_fidelity"] = "TOP_OF_BOOK_DEPTH_PROXY_NOT_SEQUENCE_L2"
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, raw_score=raw, inputs=inputs)
        score = _clip(abs(raw) * 1.8)
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        move = atr_bps * _horizon_scale(horizon_seconds, cap=1.8) * (0.35 + 0.62 * score)
        return self._emit(features, horizon_seconds, sign=sign, score=score, expected_move_bps=move, cost=cost,
                          reason="macrohft_microstructure_proxy_passed", inputs=inputs, probability_ceiling=0.72)


class WebCryptoMarketContextProxy(FederatedResearchModel):
    model_id = "candidate_webcrypto_market_context_proxy_v1"
    hypothesis = "webcryptoagent_style_market_context_proxy"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="webcryptoagent",
        role="FEDERATED",
        implementation="deterministic_market_context_consensus_proxy",
        fidelity="MARKET_CONTEXT_ONLY_NO_LLM_NEWS_OR_ONCHAIN",
        external_runtime=False,
        training_mode="frozen_rules",
    )

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        return_sign = _signed(features.return_5)
        trend_sign = _signed(features.trend_slope)
        book_sign = _signed(features.book_imbalance)
        votes = [value for value in (return_sign, trend_sign, book_sign) if value]
        vote_sum = sum(votes)
        sign = _signed(vote_sum)
        agreement = abs(vote_sum) / max(1, len(votes))
        if len(votes) < 2:
            reasons.append("context_inputs_insufficient")
        if agreement < 0.66:
            reasons.append("context_consensus_low")
        if float(features.volume_zscore or -9.0) < -0.5:
            reasons.append("context_participation_weak")
        if float(features.data_quality or 0.0) < 0.99:
            reasons.append("context_quality_low")
        inputs = self._inputs(features, cost)
        inputs.update({
            "vote_return": return_sign, "vote_trend": trend_sign, "vote_book": book_sign,
            "agreement": agreement, "external_context": "UNAVAILABLE_NOT_INFERRED",
        })
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, raw_score=agreement, inputs=inputs)
        quality = _clip(float(features.data_quality or 0.0))
        liquidity = 1.0 - _clip(float(features.spread_bps or 100.0) / 50.0)
        score = _clip(0.55 * agreement + 0.25 * quality + 0.20 * liquidity)
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        move = atr_bps * _horizon_scale(horizon_seconds) * (0.36 + 0.68 * score)
        return self._emit(features, horizon_seconds, sign=sign, score=score, expected_move_bps=move, cost=cost,
                          reason="webcrypto_market_context_proxy_passed", inputs=inputs, probability_ceiling=0.73)


class CexMultiHorizonMarketOracle(FederatedResearchModel):
    model_id = "candidate_cex_multi_horizon_oracle_v1"
    hypothesis = "cex_multi_horizon_market_oracle"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="cex_market_oracle",
        role="FEDERATED_CHALLENGER",
        implementation="phase1_observation_snapshot_multi_horizon_oracle",
        fidelity="LOCAL_CEX_HISTORY_ONLY_NO_EXECUTION",
        external_runtime=False,
        training_mode="frozen_rules_then_walk_forward_calibration",
    )

    HORIZON_WEIGHTS = {
        "1h": 0.34,
        "5h": 0.26,
        "24h": 0.20,
        "7d": 0.12,
        "30d": 0.08,
    }

    def __init__(
        self,
        cost_model: ResearchCostModel,
        *,
        min_data_quality: float = 0.99,
        minimum_edge_multiple: float = 1.25,
        score_scale: float = 1.0,
        min_horizons: int = 2,
        min_agreement: float = 0.56,
        min_signal_bps: float = 6.0,
        max_spread_bps: float = 20.0,
        max_spread_stability_ratio: float = 3.0,
        min_depth_usd_25bps: float = 25_000.0,
    ) -> None:
        super().__init__(
            cost_model,
            min_data_quality=min_data_quality,
            minimum_edge_multiple=minimum_edge_multiple,
            score_scale=score_scale,
        )
        self.min_horizons = max(1, int(min_horizons))
        self.min_agreement = _clip(min_agreement)
        self.min_signal_bps = max(0.0, float(min_signal_bps))
        self.max_spread_bps = max(0.0, float(max_spread_bps))
        self.max_spread_stability_ratio = max(1.0, float(max_spread_stability_ratio))
        self.min_depth_usd_25bps = max(0.0, float(min_depth_usd_25bps))

    @staticmethod
    def _float(value: Any) -> float | None:
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        values = features.values if isinstance(features.values, dict) else {}
        oracle = values.get("cex_market_oracle") if isinstance(values.get("cex_market_oracle"), dict) else {}
        horizons = oracle.get("horizons") if isinstance(oracle.get("horizons"), dict) else {}
        latest = oracle.get("latest") if isinstance(oracle.get("latest"), dict) else {}
        stability = oracle.get("stability") if isinstance(oracle.get("stability"), dict) else {}

        weighted_change = 0.0
        vote_sum = 0.0
        total_weight = 0.0
        available: dict[str, dict[str, Any]] = {}
        for label, weight in self.HORIZON_WEIGHTS.items():
            row = horizons.get(label) if isinstance(horizons.get(label), dict) else {}
            change_bps = self._float(row.get("change_bps"))
            if not row.get("available") or change_bps is None:
                continue
            available[label] = dict(row)
            weighted_change += float(weight) * float(change_bps)
            vote_sum += float(weight) * _signed(change_bps if abs(change_bps) >= 1.5 else 0.0)
            total_weight += float(weight)

        if len(available) < self.min_horizons:
            reasons.append("oracle_insufficient_horizon_history")
        sign = _signed(vote_sum)
        agreement = abs(vote_sum) / max(0.000001, total_weight)
        if sign == 0:
            reasons.append("oracle_direction_unavailable")
        if agreement < self.min_agreement:
            reasons.append("oracle_horizon_agreement_low")
        if abs(weighted_change) < self.min_signal_bps:
            reasons.append("oracle_signal_too_small")

        latest_spread = self._float(latest.get("spread_bps"))
        latest_depth = self._float(latest.get("depth_usd_25bps"))
        spread_stability = self._float(stability.get("spread_stability_ratio"))
        if latest_spread is not None and latest_spread > self.max_spread_bps:
            reasons.append("oracle_spread_too_wide")
        if latest_depth is not None and latest_depth < self.min_depth_usd_25bps:
            reasons.append("oracle_depth_too_thin")
        if spread_stability is not None and spread_stability > self.max_spread_stability_ratio:
            reasons.append("oracle_spread_unstable")

        inputs = self._inputs(features, cost)
        inputs["cex_market_oracle"] = {
            "schema": "phase2_cex_market_oracle_forecast_v1",
            "source_context": oracle,
            "available_horizons": sorted(available.keys()),
            "horizon_weights": dict(self.HORIZON_WEIGHTS),
            "weighted_change_bps": round(weighted_change, 6),
            "vote_sum": round(vote_sum, 6),
            "agreement": round(agreement, 6),
            "direction_sign": sign,
            "authority": "research_forecast_only",
            "execution_eligible": False,
            "orders_submitted": 0,
        }
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, raw_score=agreement, inputs=inputs)

        signal_strength = _clip(abs(weighted_change) / 80.0)
        spread_score = 1.0
        if latest_spread is not None and self.max_spread_bps > 0:
            spread_score = _clip(1.0 - latest_spread / self.max_spread_bps)
        stability_score = 1.0
        if spread_stability is not None and self.max_spread_stability_ratio > 1.0:
            stability_score = _clip(1.0 - (spread_stability - 1.0) / (self.max_spread_stability_ratio - 1.0))
        score = self.score_scale * _clip(
            0.46 * agreement
            + 0.32 * signal_strength
            + 0.12 * spread_score
            + 0.10 * stability_score,
            0.0,
            1.2,
        )
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        evidence_projection_bps = abs(weighted_change) * (0.12 + 0.06 * _horizon_scale(horizon_seconds, cap=1.6))
        atr_projection_bps = atr_bps * _horizon_scale(horizon_seconds, cap=1.6) * (0.24 + 0.42 * _clip(score))
        move = min(max(evidence_projection_bps, atr_projection_bps), max(8.0, abs(weighted_change) * 0.58))
        inputs["cex_market_oracle"]["score"] = round(score, 6)
        inputs["cex_market_oracle"]["move_components_bps"] = {
            "evidence_projection": round(evidence_projection_bps, 6),
            "atr_projection": round(atr_projection_bps, 6),
            "bounded_move": round(move, 6),
        }
        return self._emit(
            features,
            horizon_seconds,
            sign=sign,
            score=score,
            expected_move_bps=move,
            cost=cost,
            reason="cex_multi_horizon_oracle_passed",
            inputs=inputs,
            probability_ceiling=0.74,
        )


class TriunePolyphonicSynthesisCandidate(FederatedResearchModel):
    model_id = "candidate_triune_polyphonic_synthesis_v1"
    hypothesis = "governed_multi_system_market_synthesis"
    descriptor = FederatedModelDescriptor(
        model_id=model_id,
        family="phoenix_advanced_synthesis",
        role="FEDERATED_CHALLENGER",
        implementation="vns_cce_triune_polyphonic_seraph_sophia_mandos_adapter",
        fidelity="DETERMINISTIC_LOCAL_REPRODUCTION_WITH_SOURCE_FINGERPRINTS",
        external_runtime=False,
        training_mode="frozen_rules_then_walk_forward_calibration",
    )

    def __init__(
        self,
        cost_model: ResearchCostModel,
        *,
        min_data_quality: float = 0.99,
        minimum_edge_multiple: float = 1.25,
        score_scale: float = 1.0,
        source_roots: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            cost_model,
            min_data_quality=min_data_quality,
            minimum_edge_multiple=minimum_edge_multiple,
            score_scale=score_scale,
        )
        self.synthesizer = AdvancedSystemsMarketSynthesizer(
            source_roots=source_roots,
            minimum_edge_multiple=minimum_edge_multiple,
        )

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        reasons = self._base_reasons(features, cost)
        receipt = self.synthesizer.synthesize(features, cost, horizon_seconds=horizon_seconds)
        reasons.extend(str(reason) for reason in receipt["refusal_reasons"])
        inputs = self._inputs(features, cost)
        inputs["advanced_systems_synthesis"] = receipt
        score = float(receipt["score"]) * self.score_scale
        if reasons or not receipt["accepted"]:
            return self._abstain(
                features,
                horizon_seconds,
                reasons or ["advanced_systems_synthesis_refused"],
                cost=cost,
                raw_score=score,
                inputs=inputs,
            )
        return self._emit(
            features,
            horizon_seconds,
            sign=int(receipt["direction_sign"]),
            score=score,
            expected_move_bps=float(receipt["expected_move_bps"]),
            cost=cost,
            reason="advanced_systems_synthesis_passed",
            inputs=inputs,
            probability_ceiling=0.72,
        )


class ResearchModelFederation:
    MODEL_TYPES = (
        FreqtradeBreakoutAdapter,
        JesseTrendPullbackAdapter,
        FreqAITransparentLinearCandidate,
        FinRLConservativePolicyProxy,
        MacroHFTRegimeMicrostructureProxy,
        WebCryptoMarketContextProxy,
        CexMultiHorizonMarketOracle,
        TriunePolyphonicSynthesisCandidate,
    )

    def __init__(self, cfg: Any, cost_model: ResearchCostModel) -> None:
        self.enabled = bool(getattr(cfg, "phase2_federation_enabled", True))
        configured = getattr(cfg, "phase2_federation_models", None) or [cls.model_id for cls in self.MODEL_TYPES]
        selected = {str(item).strip() for item in configured if str(item).strip()}
        quarantined_config = getattr(cfg, "phase2_federation_quarantined_models", {}) or {}
        if isinstance(quarantined_config, Mapping):
            self.quarantined_models = {
                str(model_id).strip(): str(reason).strip()
                for model_id, reason in quarantined_config.items()
                if str(model_id).strip()
            }
        else:
            self.quarantined_models = {
                str(model_id).strip(): "quarantined_by_configuration"
                for model_id in quarantined_config
                if str(model_id).strip()
            }
        selected.difference_update(self.quarantined_models)
        min_quality = float(getattr(cfg, "phase2_federation_min_data_quality", getattr(cfg, "phase2_min_data_quality", 0.99)) or 0.99)
        edge_multiple = float(getattr(cfg, "phase2_federation_minimum_edge_multiple", 1.25) or 1.25)
        score_scale = float(getattr(cfg, "phase2_federation_score_scale", 1.0) or 1.0)
        freqai_confidence_floor = float(getattr(cfg, "phase2_federation_freqai_confidence_floor", 0.40) or 0.40)
        source_roots = getattr(cfg, "phase2_advanced_system_source_roots", {}) or {}
        self.models = tuple(
            cls(
                cost_model,
                min_data_quality=min_quality,
                minimum_edge_multiple=edge_multiple,
                score_scale=score_scale,
                confidence_floor=freqai_confidence_floor,
            ) if cls is FreqAITransparentLinearCandidate else cls(
                cost_model,
                min_data_quality=min_quality,
                minimum_edge_multiple=edge_multiple,
                score_scale=score_scale,
                source_roots=source_roots,
            ) if cls is TriunePolyphonicSynthesisCandidate else cls(
                cost_model,
                min_data_quality=min_quality,
                minimum_edge_multiple=edge_multiple,
                score_scale=score_scale,
            )
            for cls in self.MODEL_TYPES
            if cls.model_id in selected
        ) if self.enabled else ()

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(model.model_id for model in self.models)

    def manifest(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": "live_research_forecasts_only",
            "model_count": len(self.models),
            "models": [model.descriptor.to_dict() for model in self.models],
            "quarantined_models": dict(self.quarantined_models),
            "external_execution_runtimes_started": 0,
            "private_api_wired": False,
            "execution_wired": False,
            "orders_submitted": 0,
            "authority": "none",
        }
