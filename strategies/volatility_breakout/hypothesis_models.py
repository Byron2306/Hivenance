from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from typing import Iterable, Protocol

from .cost_model import CostEstimate, ResearchCostModel
from .models import FeatureVector, Forecast


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _signed(value: float | None) -> int:
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def _direction(sign: int) -> str:
    return "UP" if sign > 0 else "DOWN" if sign < 0 else "ABSTAIN"


def _probability(score: float, *, floor: float = 0.50, ceiling: float = 0.82) -> float:
    return round(floor + (ceiling - floor) * _clip(score), 6)


def _regime_inputs(features: FeatureVector) -> dict:
    values = features.values if isinstance(features.values, dict) else {}
    regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
    return regime_inputs


def _infer_regime_inputs(features: FeatureVector) -> dict:
    vol = float(features.volatility_expansion or 0.0)
    trend = float(features.trend_slope or 0.0)
    volume = float(features.volume_zscore or 0.0)
    ret_z = float(features.return_zscore or 0.0)
    spread = float(features.spread_bps or 0.0)
    depth = float(features.depth_usd_25bps or 0.0)
    range_pos = features.range_position if features.range_position is not None else 0.5

    if vol >= 1.35 and abs(trend) >= 0.000003:
        regime = "trend_expansion"
    elif vol >= 1.20 and (range_pos >= 0.85 or range_pos <= 0.15) and abs(ret_z) >= 1.0:
        regime = "stretch_exhaustion"
    elif spread > 12.0 or depth < 250_000.0:
        regime = "hostile_liquidity"
    elif abs(trend) < 0.000001 and 0.25 <= range_pos <= 0.75 and vol <= 0.85:
        regime = "quiet_range"
    else:
        regime = "balanced_transition"

    confidence = round(
        max(
            0.2,
            min(
                0.95,
                0.45
                + min(0.2, abs(trend) * 20_000.0)
                + min(0.15, abs(vol - 1.0) * 0.35)
                + min(0.15, abs(ret_z) * 0.05),
            ),
        ),
        3,
    )
    return {"regime_hint": regime, "confidence": confidence, "inferred": True}


def _regime_hint(features: FeatureVector) -> str:
    regime_inputs = _regime_inputs(features)
    if not regime_inputs:
        regime_inputs = _infer_regime_inputs(features)
    hint = regime_inputs.get("regime_hint")
    return str(hint or "unknown")


def _regime_confidence(features: FeatureVector) -> float:
    regime_inputs = _regime_inputs(features)
    if not regime_inputs:
        regime_inputs = _infer_regime_inputs(features)
    try:
        return float(regime_inputs.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _value_float(values: dict, key: str, default: float = 0.0) -> float:
    try:
        raw = values.get(key, default)
        if raw is None:
            return float(default)
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _tradability_context(features: FeatureVector) -> dict[str, float]:
    values = features.values if isinstance(features.values, dict) else {}
    spread_bps = float(features.spread_bps or 0.0)
    depth_usd = float(features.depth_usd_25bps or 0.0)
    volume_24h = float(features.quote_volume_24h or 0.0)
    spread_score = _clip(1.0 - spread_bps / 24.0)
    depth_score = _clip(depth_usd / 1_250_000.0)
    volume_score = _clip(volume_24h / 80_000_000.0)
    participation_score = _clip((_value_float(values, "volume_zscore", -1.0) + 0.5) / 3.0)
    tradability_score = (
        0.34 * spread_score
        + 0.28 * depth_score
        + 0.20 * volume_score
        + 0.18 * participation_score
    )
    return {
        "spread_score": round(spread_score, 6),
        "depth_score": round(depth_score, 6),
        "volume_score": round(volume_score, 6),
        "participation_score": round(participation_score, 6),
        "tradability_score": round(_clip(tradability_score), 6),
    }


def _cohort_bucket(features: FeatureVector) -> str:
    values = features.values if isinstance(features.values, dict) else {}
    return str(values.get("cohort_bucket") or "unknown")


def _adaptive_policy(features: FeatureVector, model_family: str) -> dict[str, float | bool | str]:
    values = features.values if isinstance(features.values, dict) else {}
    policy_map = values.get("phase2_adaptive_thresholds") if isinstance(values.get("phase2_adaptive_thresholds"), dict) else {}
    scoped = policy_map.get(model_family) if isinstance(policy_map.get(model_family), dict) else {}
    return {str(key): value for key, value in scoped.items()}


def _abstain(
    features: FeatureVector,
    model_id: str,
    hypothesis: str,
    horizon_seconds: int,
    reasons: Iterable[str],
    *,
    cost: CostEstimate | None = None,
    raw_score: float | None = None,
    inputs: dict | None = None,
) -> Forecast:
    reason_list = tuple(str(item) for item in reasons if item)
    return Forecast(
        symbol=features.symbol,
        timestamp_ms=features.timestamp_ms,
        horizon_seconds=horizon_seconds,
        model_id=model_id,
        hypothesis=hypothesis,
        direction="ABSTAIN",
        probability_positive_net=None,
        expected_move_bps=None,
        expected_cost_bps=cost.total_bps if cost else None,
        expected_net_bps=None,
        raw_score=raw_score,
        uncertainty=1.0,
        calibration_state="COLD_START",
        feature_version="phase2.v1",
        abstain=True,
        reason=reason_list[0] if reason_list else "abstain",
        reasons=reason_list,
        inputs=inputs or {},
        execution_eligible=False,
    )


def _near_miss_summary(criteria: dict[str, float], *, threshold: float = 0.6) -> dict:
    scores = {key: round(max(0.0, min(1.0, float(value))), 6) for key, value in criteria.items()}
    return {
        "score": round(sum(scores.values()) / max(1, len(scores)), 6),
        "threshold": threshold,
        "criteria": scores,
        "closest_passes": sorted(scores, key=lambda key: scores[key], reverse=True)[:3],
        "largest_gaps": sorted(scores, key=lambda key: scores[key])[:3],
    }


class HypothesisModel(Protocol):
    model_id: str
    hypothesis: str
    is_baseline: bool

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast: ...


class BreakoutContinuationModel:
    model_id = "breakout_continuation_v1"
    hypothesis = "breakout_continuation"
    is_baseline = False

    def __init__(
        self,
        cost_model: ResearchCostModel,
        *,
        min_data_quality: float = 0.99,
        min_expansion: float = 1.25,
        min_volume_zscore: float = 0.50,
        min_return_zscore: float = 0.75,
        minimum_edge_multiple: float = 2.0,
        allowed_regimes: tuple[str, ...] = ("trend_expansion", "balanced_transition"),
        min_regime_confidence: float = 0.35,
        min_tradability_score: float = 0.55,
        min_momentum_consistency: float = 0.55,
    ) -> None:
        self.cost_model = cost_model
        self.min_data_quality = min_data_quality
        self.min_expansion = min_expansion
        self.min_volume_zscore = min_volume_zscore
        self.min_return_zscore = min_return_zscore
        self.minimum_edge_multiple = minimum_edge_multiple
        self.allowed_regimes = tuple(str(item) for item in allowed_regimes)
        self.min_regime_confidence = max(0.0, float(min_regime_confidence))
        self.min_tradability_score = _clip(min_tradability_score)
        self.min_momentum_consistency = _clip(min_momentum_consistency)

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        reasons: list[str] = []
        adaptive = _adaptive_policy(features, "breakout")
        min_expansion = max(1.0, float(adaptive.get("min_expansion", self.min_expansion) or self.min_expansion))
        min_return_zscore = max(0.25, float(adaptive.get("min_return_zscore", self.min_return_zscore) or self.min_return_zscore))
        min_regime_confidence = max(0.0, float(adaptive.get("min_regime_confidence", self.min_regime_confidence) or self.min_regime_confidence))
        min_tradability_score = _clip(float(adaptive.get("min_tradability_score", self.min_tradability_score) or self.min_tradability_score))
        min_momentum_consistency = _clip(float(adaptive.get("min_momentum_consistency", self.min_momentum_consistency) or self.min_momentum_consistency))
        minimum_edge_multiple = max(1.0, float(adaptive.get("minimum_edge_multiple", self.minimum_edge_multiple) or self.minimum_edge_multiple))
        regime_hint = _regime_hint(features)
        regime_confidence = _regime_confidence(features)
        tradability = _tradability_context(features)
        tradability_score = float(tradability["tradability_score"])
        sign = _signed(features.return_5)
        trend_alignment = 0.5
        if features.trend_slope is not None and sign != 0:
            trend_alignment = 1.0 if features.trend_slope * sign > 0 else 0.0
        book_alignment = 0.5
        if features.book_imbalance is not None and sign != 0:
            book_alignment = _clip(0.5 + 0.5 * float(features.book_imbalance) * sign)
        momentum_consistency = _clip(float(features.momentum_consistency or 0.0))
        structural_quality = _clip(
            0.32 * trend_alignment
            + 0.20 * book_alignment
            + 0.24 * momentum_consistency
            + 0.24 * tradability_score
        )
        near_miss = _near_miss_summary({
            "regime_fit": 1.0 if regime_hint in self.allowed_regimes else 0.0,
            "regime_confidence": _clip(regime_confidence / max(0.000001, min_regime_confidence)),
            "expansion": _clip((float(features.volatility_expansion or 0.0)) / max(min_expansion, 0.000001)),
            "participation": _clip((float(features.volume_zscore or -2.0) - self.min_volume_zscore + 1.0) / 2.0),
            "directional_move": _clip(abs(float(features.return_zscore or 0.0)) / max(min_return_zscore * 2.0, 0.000001)),
            "trend_alignment": trend_alignment,
            "book_alignment": book_alignment,
            "tradability": _clip(tradability_score / max(min_tradability_score, 0.000001)),
            "momentum_coherence": _clip(momentum_consistency / max(min_momentum_consistency, 0.000001)),
            "structure_quality": structural_quality,
        })
        if not features.complete:
            reasons.append("features_incomplete")
        if features.data_quality < self.min_data_quality:
            reasons.append("data_quality_below_gate")
        if regime_hint not in self.allowed_regimes:
            reasons.append("breakout_regime_mismatch")
        if regime_confidence < min_regime_confidence:
            reasons.append("regime_confidence_below_gate")
        if features.volatility_expansion is None or features.volatility_expansion < min_expansion:
            reasons.append("volatility_not_expanding")
        if features.volume_zscore is None or features.volume_zscore < self.min_volume_zscore:
            reasons.append("participation_not_confirmed")
        if features.return_zscore is None or abs(features.return_zscore) < min_return_zscore:
            reasons.append("directional_move_not_material")
        if sign == 0:
            reasons.append("direction_unavailable")
        if tradability_score < min_tradability_score:
            reasons.append("breakout_tradability_too_low")
        if momentum_consistency < min_momentum_consistency:
            reasons.append("momentum_not_persistent")
        if structural_quality < 0.58:
            reasons.append("breakout_structure_not_coherent")

        cost = self.cost_model.estimate(features)
        if not cost.tradable:
            reasons.append(cost.reason)
        inputs = {
            "volatility_expansion": features.volatility_expansion,
            "volume_zscore": features.volume_zscore,
            "return_zscore": features.return_zscore,
            "return_5": features.return_5,
            "book_imbalance": features.book_imbalance,
            "trend_slope": features.trend_slope,
            "momentum_consistency": features.momentum_consistency,
            "regime_hint": regime_hint,
            "regime_confidence": regime_confidence,
            "cohort_bucket": _cohort_bucket(features),
            "adaptive_policy": adaptive,
            "tradability": tradability,
            "structural_quality": round(structural_quality, 6),
            "cost": asdict(cost),
            "near_miss": near_miss,
        }
        if reasons:
            return _abstain(features, self.model_id, self.hypothesis, horizon_seconds, reasons, cost=cost, inputs=inputs)

        expansion_score = _clip((float(features.volatility_expansion) - 1.0) / 2.5)
        volume_score = _clip((float(features.volume_zscore) + 0.5) / 3.5)
        return_score = _clip(abs(float(features.return_zscore)) / 3.0)
        momentum_score = _clip(float(features.momentum_consistency or 0.0))
        score = (
            0.20 * expansion_score
            + 0.15 * volume_score
            + 0.20 * return_score
            + 0.14 * momentum_score
            + 0.10 * trend_alignment
            + 0.09 * book_alignment
            + 0.12 * tradability_score
            + 0.10 * structural_quality
        )
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        expected_move = atr_bps * (0.65 + 0.95 * score)
        expected_net = expected_move - cost.total_bps
        edge_multiple = expected_move / max(cost.total_bps, 0.000001)
        probability = _probability(score)
        if expected_net <= 0 or edge_multiple < minimum_edge_multiple:
            reasons = ["insufficient_cost_adjusted_edge"]
            return _abstain(
                features, self.model_id, self.hypothesis, horizon_seconds, reasons,
                cost=cost, raw_score=score, inputs={**inputs, "edge_multiple": edge_multiple, "near_miss": near_miss},
            )

        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=horizon_seconds,
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            direction=_direction(sign),
            probability_positive_net=probability,
            expected_move_bps=round(expected_move, 6),
            expected_cost_bps=cost.total_bps,
            expected_net_bps=round(expected_net, 6),
            raw_score=round(score, 6),
            uncertainty=round(1.0 - score, 6),
            calibration_state="COLD_START_PROVISIONAL",
            feature_version="phase2.v1",
            abstain=False,
            reason="breakout_hypothesis_passed",
            reasons=(),
            inputs={**inputs, "edge_multiple": round(edge_multiple, 6), "near_miss": near_miss},
            execution_eligible=False,
        )


class ExhaustionMeanReversionModel:
    model_id = "exhaustion_mean_reversion_v1"
    hypothesis = "exhaustion_mean_reversion"
    is_baseline = False

    def __init__(
        self,
        cost_model: ResearchCostModel,
        *,
        min_data_quality: float = 0.99,
        min_stretch_zscore: float = 1.50,
        min_range_extreme: float = 0.85,
        minimum_edge_multiple: float = 2.0,
        allowed_regimes: tuple[str, ...] = ("stretch_exhaustion", "quiet_range", "balanced_transition"),
        min_regime_confidence: float = 0.30,
        min_tradability_score: float = 0.50,
        min_reversal_strength: float = 0.30,
    ) -> None:
        self.cost_model = cost_model
        self.min_data_quality = min_data_quality
        self.min_stretch_zscore = min_stretch_zscore
        self.min_range_extreme = min_range_extreme
        self.minimum_edge_multiple = minimum_edge_multiple
        self.allowed_regimes = tuple(str(item) for item in allowed_regimes)
        self.min_regime_confidence = max(0.0, float(min_regime_confidence))
        self.min_tradability_score = _clip(min_tradability_score)
        self.min_reversal_strength = _clip(min_reversal_strength)

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        reasons: list[str] = []
        adaptive = _adaptive_policy(features, "reversion")
        min_stretch_zscore = max(0.5, float(adaptive.get("min_stretch_zscore", self.min_stretch_zscore) or self.min_stretch_zscore))
        min_range_extreme = _clip(float(adaptive.get("min_range_extreme", self.min_range_extreme) or self.min_range_extreme), 0.5, 0.99)
        min_regime_confidence = max(0.0, float(adaptive.get("min_regime_confidence", self.min_regime_confidence) or self.min_regime_confidence))
        min_tradability_score = _clip(float(adaptive.get("min_tradability_score", self.min_tradability_score) or self.min_tradability_score))
        min_reversal_strength = _clip(float(adaptive.get("min_reversal_strength", self.min_reversal_strength) or self.min_reversal_strength))
        minimum_edge_multiple = max(1.0, float(adaptive.get("minimum_edge_multiple", self.minimum_edge_multiple) or self.minimum_edge_multiple))
        regime_hint = _regime_hint(features)
        regime_confidence = _regime_confidence(features)
        tradability = _tradability_context(features)
        tradability_score = float(tradability["tradability_score"])
        stretch = features.return_zscore if features.return_zscore is not None else features.price_zscore
        stretch_sign = _signed(stretch)
        sign = -stretch_sign
        reversal_confirmed = False
        if features.reversal_return_1 is not None and stretch_sign:
            reversal_confirmed = features.reversal_return_1 * stretch_sign < 0
        if features.book_imbalance is not None and stretch_sign:
            reversal_confirmed = reversal_confirmed or features.book_imbalance * stretch_sign < -0.05
        book_score = 0.5
        if features.book_imbalance is not None and sign != 0:
            book_score = _clip(0.5 + 0.5 * float(features.book_imbalance) * sign)
        reversal_score = 0.5
        if features.reversal_return_1 is not None:
            reversal_score = _clip(abs(float(features.reversal_return_1)) * 10_000.0 / 30.0)
        expansion_score = _clip((float(features.volatility_expansion or 1.0) - 0.8) / 2.5)
        exhaustion_quality = _clip(
            0.30 * reversal_score
            + 0.20 * book_score
            + 0.25 * tradability_score
            + 0.25 * _clip(abs(float(stretch or 0.0)) / max(min_stretch_zscore * 1.5, 0.000001))
        )
        near_miss = _near_miss_summary({
            "regime_fit": 1.0 if regime_hint in self.allowed_regimes else 0.0,
            "regime_confidence": _clip(regime_confidence / max(0.000001, min_regime_confidence)),
            "stretch": _clip(abs(float(stretch or 0.0)) / max(min_stretch_zscore * 2.0, 0.000001)),
            "range_extreme": _clip(abs(float(features.range_position or 0.5) - 0.5) * 2.0 / max(min_range_extreme, 0.000001)),
            "reversal": 1.0 if reversal_confirmed else reversal_score,
            "book_alignment": book_score,
            "volatility_context": expansion_score,
            "tradability": _clip(tradability_score / max(min_tradability_score, 0.000001)),
            "reversal_strength": _clip(reversal_score / max(min_reversal_strength, 0.000001)),
            "exhaustion_quality": exhaustion_quality,
        })
        if not features.complete:
            reasons.append("features_incomplete")
        if features.data_quality < self.min_data_quality:
            reasons.append("data_quality_below_gate")
        if regime_hint not in self.allowed_regimes:
            reasons.append("reversion_regime_mismatch")
        if regime_confidence < min_regime_confidence:
            reasons.append("regime_confidence_below_gate")
        if stretch is None or abs(stretch) < min_stretch_zscore:
            reasons.append("stretch_not_extreme")
        if features.range_position is None:
            reasons.append("range_position_unavailable")
        elif not (features.range_position >= min_range_extreme or features.range_position <= 1.0 - min_range_extreme):
            reasons.append("price_not_at_range_extreme")

        if sign == 0:
            reasons.append("reversion_direction_unavailable")

        # Require a first sign of exhaustion rather than blindly fading strength.
        if not reversal_confirmed:
            reasons.append("exhaustion_not_confirmed")
        if tradability_score < min_tradability_score:
            reasons.append("reversion_tradability_too_low")
        if reversal_score < min_reversal_strength:
            reasons.append("reversal_strength_too_low")
        if exhaustion_quality < 0.54:
            reasons.append("reversion_setup_not_coherent")

        cost = self.cost_model.estimate(features)
        if not cost.tradable:
            reasons.append(cost.reason)
        inputs = {
            "stretch_zscore": stretch,
            "return_zscore": features.return_zscore,
            "price_zscore": features.price_zscore,
            "range_position": features.range_position,
            "reversal_return_1": features.reversal_return_1,
            "book_imbalance": features.book_imbalance,
            "volatility_expansion": features.volatility_expansion,
            "regime_hint": regime_hint,
            "regime_confidence": regime_confidence,
            "cohort_bucket": _cohort_bucket(features),
            "adaptive_policy": adaptive,
            "tradability": tradability,
            "exhaustion_quality": round(exhaustion_quality, 6),
            "cost": asdict(cost),
            "near_miss": near_miss,
        }
        if reasons:
            return _abstain(features, self.model_id, self.hypothesis, horizon_seconds, reasons, cost=cost, inputs=inputs)

        stretch_score = _clip((abs(float(stretch)) - 1.0) / 3.0)
        extreme_score = _clip(abs(float(features.range_position) - 0.5) * 2.0)
        score = (
            0.26 * stretch_score
            + 0.18 * extreme_score
            + 0.20 * reversal_score
            + 0.10 * book_score
            + 0.08 * expansion_score
            + 0.10 * tradability_score
            + 0.08 * exhaustion_quality
        )
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        expected_move = atr_bps * (0.55 + 0.85 * score)
        expected_net = expected_move - cost.total_bps
        edge_multiple = expected_move / max(cost.total_bps, 0.000001)
        probability = _probability(score, floor=0.50, ceiling=0.78)
        if expected_net <= 0 or edge_multiple < minimum_edge_multiple:
            return _abstain(
                features, self.model_id, self.hypothesis, horizon_seconds,
                ["insufficient_cost_adjusted_edge"], cost=cost, raw_score=score,
                inputs={**inputs, "edge_multiple": edge_multiple, "near_miss": near_miss},
            )

        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=horizon_seconds,
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            direction=_direction(sign),
            probability_positive_net=probability,
            expected_move_bps=round(expected_move, 6),
            expected_cost_bps=cost.total_bps,
            expected_net_bps=round(expected_net, 6),
            raw_score=round(score, 6),
            uncertainty=round(1.0 - score, 6),
            calibration_state="COLD_START_PROVISIONAL",
            feature_version="phase2.v1",
            abstain=False,
            reason="mean_reversion_hypothesis_passed",
            reasons=(),
            inputs={**inputs, "edge_multiple": round(edge_multiple, 6), "near_miss": near_miss},
            execution_eligible=False,
        )


class NoTradeBaseline:
    model_id = "baseline_no_trade_v1"
    hypothesis = "baseline_no_trade"
    is_baseline = True

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        return _abstain(features, self.model_id, self.hypothesis, horizon_seconds, ["baseline_no_trade"])


class SimpleMomentumBaseline:
    model_id = "baseline_simple_momentum_v1"
    hypothesis = "baseline_simple_momentum"
    is_baseline = True

    def __init__(self, cost_model: ResearchCostModel) -> None:
        self.cost_model = cost_model

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        sign = _signed(features.return_5)
        cost = self.cost_model.estimate(features)
        if not features.complete or sign == 0 or not cost.tradable:
            return _abstain(features, self.model_id, self.hypothesis, horizon_seconds, ["baseline_unavailable"], cost=cost)
        move = abs(float(features.return_5 or 0.0)) * 10_000.0
        return Forecast(
            symbol=features.symbol, timestamp_ms=features.timestamp_ms, horizon_seconds=horizon_seconds,
            model_id=self.model_id, hypothesis=self.hypothesis, direction=_direction(sign),
            probability_positive_net=0.55, expected_move_bps=round(move, 6),
            expected_cost_bps=cost.total_bps, expected_net_bps=round(move - cost.total_bps, 6),
            raw_score=0.5, uncertainty=0.5, calibration_state="BASELINE_FIXED",
            feature_version="phase2.v1", abstain=False, reason="baseline_momentum",
            inputs={"return_5": features.return_5}, execution_eligible=False,
        )


class SimpleMeanReversionBaseline:
    model_id = "baseline_simple_mean_reversion_v1"
    hypothesis = "baseline_simple_mean_reversion"
    is_baseline = True

    def __init__(self, cost_model: ResearchCostModel) -> None:
        self.cost_model = cost_model

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        stretch = features.return_zscore
        sign = -_signed(stretch)
        cost = self.cost_model.estimate(features)
        if not features.complete or stretch is None or abs(stretch) < 1.0 or sign == 0 or not cost.tradable:
            return _abstain(features, self.model_id, self.hypothesis, horizon_seconds, ["baseline_unavailable"], cost=cost)
        move = max(0.0, float(features.atr_pct or 0.0) * 10_000.0)
        return Forecast(
            symbol=features.symbol, timestamp_ms=features.timestamp_ms, horizon_seconds=horizon_seconds,
            model_id=self.model_id, hypothesis=self.hypothesis, direction=_direction(sign),
            probability_positive_net=0.55, expected_move_bps=round(move, 6),
            expected_cost_bps=cost.total_bps, expected_net_bps=round(move - cost.total_bps, 6),
            raw_score=0.5, uncertainty=0.5, calibration_state="BASELINE_FIXED",
            feature_version="phase2.v1", abstain=False, reason="baseline_mean_reversion",
            inputs={"return_zscore": stretch}, execution_eligible=False,
        )


class DeterministicRandomBaseline:
    model_id = "baseline_deterministic_random_v1"
    hypothesis = "baseline_random"
    is_baseline = True

    def __init__(self, cost_model: ResearchCostModel) -> None:
        self.cost_model = cost_model

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        if not features.complete or not cost.tradable:
            return _abstain(features, self.model_id, self.hypothesis, horizon_seconds, ["baseline_unavailable"], cost=cost)
        digest = hashlib.sha256(f"{features.symbol}:{features.timestamp_ms}:{horizon_seconds}".encode()).digest()
        sign = 1 if digest[0] % 2 == 0 else -1
        return Forecast(
            symbol=features.symbol, timestamp_ms=features.timestamp_ms, horizon_seconds=horizon_seconds,
            model_id=self.model_id, hypothesis=self.hypothesis, direction=_direction(sign),
            probability_positive_net=0.50, expected_move_bps=0.0, expected_cost_bps=cost.total_bps,
            expected_net_bps=-cost.total_bps, raw_score=0.0, uncertainty=1.0,
            calibration_state="BASELINE_FIXED", feature_version="phase2.v1", abstain=False,
            reason="baseline_deterministic_random", inputs={}, execution_eligible=False,
        )
