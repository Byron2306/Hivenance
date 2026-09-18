from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from agents.strategy_workers import (
    BollingerWorker,
    BreakoutWorker,
    MomentumWorker,
    RSI2Worker,
    RSIWorker,
    SMAWorker,
    SupertrendWorker,
    VolatilityExpansionWorker,
)

from .cost_model import CostEstimate, ResearchCostModel
from .models import FeatureVector, Forecast
from .triune_worker_mind import TriuneWorkerMind


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _horizon_scale(horizon_seconds: int) -> float:
    return max(0.75, min(2.50, math.sqrt(max(60, int(horizon_seconds)) / 300.0)))


def _direction(action: str) -> str:
    normalized = str(action or "").upper()
    if normalized == "BUY":
        return "UP"
    if normalized == "SELL":
        return "DOWN"
    return "ABSTAIN"


@dataclass(frozen=True)
class WorkerSignalDescriptor:
    model_id: str
    worker_id: str
    family: str
    role: str = "LEGACY_STRATEGY_WORKER_SIGNAL"
    implementation: str = "agents.strategy_workers"
    fidelity: str = "DETERMINISTIC_LOCAL_WORKER"
    authority: str = "research_forecast_only"
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkerSignalModel:
    """Converts legacy strategy worker proposals into Phase-2 forecasts.

    Workers are deliberately treated as research-only feature interpreters. They
    can propose directional hypotheses, but this bridge never grants execution.
    """

    is_baseline = False

    def __init__(
        self,
        *,
        cost_model: ResearchCostModel,
        worker: Any,
        model_id: str,
        hypothesis: str,
        family: str,
        min_data_quality: float = 0.99,
        minimum_edge_multiple: float = 1.10,
        min_strength: float = 0.45,
        score_scale: float = 1.0,
        settle_counterfactuals: bool = True,
        negative_memory_enabled: bool = True,
        negative_memory_min_samples: int = 3,
        negative_memory_max_mean_net_bps: float = -5.0,
        negative_memory_min_directional_hit_rate: float = 0.42,
        triune_mind_enabled: bool = True,
        triune_loki_enabled: bool = True,
        triune_michael_min_validation_score: float = 0.42,
        triune_loki_veto_risk: float = 0.82,
        triune_loki_challenge_risk: float = 0.45,
    ) -> None:
        self.cost_model = cost_model
        self.worker = worker
        self.model_id = model_id
        self.hypothesis = hypothesis
        self.min_data_quality = float(min_data_quality)
        self.minimum_edge_multiple = max(1.0, float(minimum_edge_multiple))
        self.min_strength = max(0.0, min(1.0, float(min_strength)))
        self.score_scale = max(0.25, float(score_scale))
        self.settle_counterfactuals = bool(settle_counterfactuals)
        self.negative_memory_enabled = bool(negative_memory_enabled)
        self.negative_memory_min_samples = max(1, int(negative_memory_min_samples))
        self.negative_memory_max_mean_net_bps = float(negative_memory_max_mean_net_bps)
        self.negative_memory_min_directional_hit_rate = max(0.0, min(1.0, float(negative_memory_min_directional_hit_rate)))
        self.triune_mind = TriuneWorkerMind(
            enabled=triune_mind_enabled,
            loki_enabled=triune_loki_enabled,
            michael_min_validation_score=triune_michael_min_validation_score,
            loki_veto_risk=triune_loki_veto_risk,
            loki_challenge_risk=triune_loki_challenge_risk,
        )
        self.descriptor = WorkerSignalDescriptor(
            model_id=model_id,
            worker_id=str(getattr(worker, "name", model_id)),
            family=family,
        )

    @staticmethod
    def _memory_key(model_id: str, horizon_seconds: int, direction: str) -> str:
        return f"{model_id}|{int(horizon_seconds)}|{direction}"

    def _series(self, features: FeatureVector) -> tuple[list[float], list[float], dict[str, Any]]:
        values = features.values if isinstance(features.values, dict) else {}
        series = values.get("worker_series") if isinstance(values.get("worker_series"), dict) else {}
        closes = [float(value) for value in (series.get("closes") or []) if _is_finite_number(value) and float(value) > 0]
        volumes = [float(value) for value in (series.get("volumes") or []) if _is_finite_number(value) and float(value) >= 0]
        if len(volumes) > len(closes):
            volumes = volumes[-len(closes):]
        return closes, volumes, dict(series)

    def _base_inputs(
        self,
        features: FeatureVector,
        cost: CostEstimate,
        proposal: Mapping[str, Any] | None,
        series: Mapping[str, Any],
        closes: Iterable[float],
        volumes: Iterable[float],
    ) -> dict[str, Any]:
        safe_closes = list(closes)
        safe_volumes = list(volumes)
        receipt = {
            "schema": "hivenance_worker_forecast_receipt_v1",
            "worker_id": self.descriptor.worker_id,
            "model_id": self.model_id,
            "family": self.descriptor.family,
            "raw_action": str((proposal or {}).get("action") or "HOLD").upper(),
            "raw_strength": round(float((proposal or {}).get("signal_strength") or 0.0), 6),
            "worker_note": str((proposal or {}).get("notes") or ""),
            "worker_risk": (proposal or {}).get("risk"),
            "series_schema": series.get("schema"),
            "series_points": len(safe_closes),
            "series_root": _stable_hash(
                {
                    "symbol": features.symbol,
                    "timeframe": series.get("timeframe"),
                    "latest_candle_ts": series.get("latest_candle_ts"),
                    "closes": [round(float(value), 12) for value in safe_closes],
                    "volumes": [round(float(value), 12) for value in safe_volumes],
                }
            ),
            "authority": "research_forecast_only",
            "bridge_authority": "proposal_only",
            "execution_authority": "none",
            "execution_eligible": False,
            "orders_submitted": 0,
        }
        return {
            "worker_signal": self.descriptor.to_dict(),
            "worker_signal_receipt": receipt,
            "cost": asdict(cost),
            "feature_version": (features.values or {}).get("feature_version", "phase2.v1"),
            "regime_inputs": (features.values or {}).get("regime_inputs", {}),
            "return_5": features.return_5,
            "return_zscore": features.return_zscore,
            "trend_slope": features.trend_slope,
            "atr_pct": features.atr_pct,
            "volatility_expansion": features.volatility_expansion,
            "volume_zscore": features.volume_zscore,
            "spread_bps": features.spread_bps,
            "depth_usd_25bps": features.depth_usd_25bps,
        }

    def _abstain(
        self,
        features: FeatureVector,
        horizon_seconds: int,
        reasons: Iterable[str],
        *,
        cost: CostEstimate,
        proposal: Mapping[str, Any] | None = None,
        series: Mapping[str, Any] | None = None,
        closes: Iterable[float] = (),
        volumes: Iterable[float] = (),
        raw_score: float | None = None,
        extra_inputs: Mapping[str, Any] | None = None,
    ) -> Forecast:
        reason_list = tuple(str(item) for item in reasons if item)
        inputs = self._base_inputs(features, cost, proposal, series or {}, closes, volumes)
        if isinstance(extra_inputs, Mapping):
            inputs.update(dict(extra_inputs))
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
            calibration_state="WORKER_SIGNAL_COLD_START",
            feature_version="phase2.worker_signal.v1",
            abstain=True,
            reason=reason_list[0] if reason_list else "worker_signal_abstain",
            reasons=reason_list,
            inputs=inputs,
            execution_eligible=False,
        )

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        closes, volumes, series = self._series(features)
        reasons: list[str] = []
        if not features.complete:
            reasons.append("features_incomplete")
        if float(features.data_quality or 0.0) < self.min_data_quality:
            reasons.append("data_quality_below_gate")
        if not cost.tradable:
            reasons.append(cost.reason)
        if len(closes) < 15:
            reasons.append("worker_series_unavailable")
        if reasons:
            return self._abstain(features, horizon_seconds, reasons, cost=cost, series=series, closes=closes, volumes=volumes)

        try:
            proposal = self.worker.propose(closes, volumes=volumes, latest_price=float(features.price or closes[-1]))
        except Exception as exc:
            return self._abstain(
                features,
                horizon_seconds,
                ["worker_proposal_failed"],
                cost=cost,
                proposal={"action": "HOLD", "signal_strength": 0.0, "notes": type(exc).__name__},
                series=series,
                closes=closes,
                volumes=volumes,
            )

        action = str(proposal.get("action") or "HOLD").upper()
        direction = _direction(action)
        strength = _clip(float(proposal.get("signal_strength") or 0.0) * self.score_scale, 0.0, 1.25)
        if direction == "ABSTAIN":
            return self._abstain(
                features,
                horizon_seconds,
                ["worker_action_hold"],
                cost=cost,
                proposal=proposal,
                series=series,
                closes=closes,
                volumes=volumes,
                raw_score=strength,
            )
        if strength < self.min_strength:
            return self._abstain(
                features,
                horizon_seconds,
                ["worker_signal_strength_below_gate"],
                cost=cost,
                proposal=proposal,
                series=series,
                closes=closes,
                volumes=volumes,
                raw_score=strength,
            )

        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        recent_move_bps = abs(float(features.return_5 or 0.0)) * 10_000.0
        zscore_bps = abs(float(features.return_zscore or 0.0)) * 8.0
        raw_projection = _horizon_scale(horizon_seconds) * (
            0.48 * atr_bps + 0.34 * recent_move_bps + 0.18 * zscore_bps
        ) * (0.35 + 0.65 * min(1.0, strength))
        expected_move_bps = min(raw_projection, max(8.0, atr_bps * _horizon_scale(horizon_seconds) * 1.75))
        expected_net_bps = expected_move_bps - float(cost.total_bps)
        edge_multiple = expected_move_bps / max(float(cost.total_bps), 0.000001)
        inputs = self._base_inputs(features, cost, proposal, series, closes, volumes)
        inputs["edge_multiple"] = round(edge_multiple, 6)
        inputs["horizon_scale"] = round(_horizon_scale(horizon_seconds), 6)
        worker_memory_root = (
            (features.values or {}).get("phase2_worker_signal_memory")
            if isinstance(features.values, dict)
            else {}
        )
        worker_memory = {}
        if isinstance(worker_memory_root, dict):
            exact_memory = worker_memory_root.get("exact") if isinstance(worker_memory_root.get("exact"), dict) else {}
            model_memory = worker_memory_root.get("model") if isinstance(worker_memory_root.get("model"), dict) else {}
            key = self._memory_key(self.model_id, horizon_seconds, direction)
            worker_memory = exact_memory.get(key) if isinstance(exact_memory.get(key), dict) else {}
            if not worker_memory:
                worker_memory = model_memory.get(key) if isinstance(model_memory.get(key), dict) else {}
        if worker_memory:
            inputs["worker_signal_memory"] = worker_memory
        triune_assessment = self.triune_mind.assess(
            features=features,
            worker_id=self.descriptor.worker_id,
            model_id=self.model_id,
            family=self.descriptor.family,
            direction=direction,
            horizon_seconds=int(horizon_seconds),
            strength=strength,
            cost=cost,
            expected_move_bps=expected_move_bps,
            expected_net_bps=expected_net_bps,
            edge_multiple=edge_multiple,
            worker_memory=worker_memory,
        )
        projection_multiplier = self.triune_mind.challenged_projection_multiplier(triune_assessment)
        if projection_multiplier < 1.0:
            expected_move_bps *= projection_multiplier
            expected_net_bps = expected_move_bps - float(cost.total_bps)
            edge_multiple = expected_move_bps / max(float(cost.total_bps), 0.000001)
            inputs["edge_multiple"] = round(edge_multiple, 6)
            inputs["triune_projection_multiplier"] = round(projection_multiplier, 6)
        inputs["triune_worker_mind"] = triune_assessment
        if self.negative_memory_enabled and worker_memory:
            samples = int(worker_memory.get("samples") or 0)
            mean_net = worker_memory.get("mean_net_bps")
            directional_hit_rate = worker_memory.get("directional_hit_rate")
            memory_blocks = (
                samples >= self.negative_memory_min_samples
                and mean_net is not None
                and float(mean_net) <= self.negative_memory_max_mean_net_bps
                and (
                    directional_hit_rate is None
                    or float(directional_hit_rate) < self.negative_memory_min_directional_hit_rate
                )
            )
            if memory_blocks:
                return self._abstain(
                    features,
                    horizon_seconds,
                    ["worker_signal_negative_memory"],
                    cost=cost,
                    proposal=proposal,
                    series=series,
                    closes=closes,
                    volumes=volumes,
                    raw_score=strength,
                    extra_inputs={"triune_worker_mind": triune_assessment},
                )
        if str(triune_assessment.get("final_verdict") or "") == "VETO":
            return self._abstain(
                features,
                horizon_seconds,
                ["worker_signal_loki_veto"],
                cost=cost,
                proposal=proposal,
                series=series,
                closes=closes,
                volumes=volumes,
                raw_score=strength,
                extra_inputs={"triune_worker_mind": triune_assessment},
            )
        if expected_net_bps <= 0 or edge_multiple < self.minimum_edge_multiple:
            if self.settle_counterfactuals:
                inputs["worker_counterfactual"] = {
                    "schema": "hivenance_worker_counterfactual_settlement_v1",
                    "purpose": "settle_directional_worker_signal_even_when_cost_gate_refuses",
                    "cost_gate_passed": False,
                    "minimum_edge_multiple": round(self.minimum_edge_multiple, 6),
                    "edge_multiple": round(edge_multiple, 6),
                    "authority": "research_settlement_only",
                    "execution_authority": "none",
                    "execution_eligible": False,
                    "orders_submitted": 0,
                }
                return Forecast(
                    symbol=features.symbol,
                    timestamp_ms=features.timestamp_ms,
                    horizon_seconds=int(horizon_seconds),
                    model_id=self.model_id,
                    hypothesis=self.hypothesis,
                    direction=direction,
                    probability_positive_net=round(0.48 + 0.14 * min(1.0, strength), 6),
                    expected_move_bps=round(expected_move_bps, 6),
                    expected_cost_bps=round(float(cost.total_bps), 6),
                    expected_net_bps=round(expected_net_bps, 6),
                    raw_score=round(strength, 6),
                    uncertainty=round(1.0 - min(1.0, strength), 6),
                    calibration_state="WORKER_SIGNAL_COUNTERFACTUAL_COST_REFUSED",
                    feature_version="phase2.worker_signal.v1",
                    abstain=False,
                    reason="worker_signal_counterfactual_cost_refused",
                    reasons=("insufficient_cost_adjusted_worker_edge",),
                    inputs=inputs,
                    execution_eligible=False,
                )
            return self._abstain(
                features,
                horizon_seconds,
                ["insufficient_cost_adjusted_worker_edge"],
                cost=cost,
                proposal=proposal,
                series=series,
                closes=closes,
                volumes=volumes,
                raw_score=strength,
            )

        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=int(horizon_seconds),
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            direction=direction,
            probability_positive_net=round(0.50 + 0.22 * min(1.0, strength), 6),
            expected_move_bps=round(expected_move_bps, 6),
            expected_cost_bps=round(float(cost.total_bps), 6),
            expected_net_bps=round(expected_net_bps, 6),
            raw_score=round(strength, 6),
            uncertainty=round(1.0 - min(1.0, strength), 6),
            calibration_state="WORKER_SIGNAL_COLD_START_PROVISIONAL",
            feature_version="phase2.worker_signal.v1",
            abstain=False,
            reason="worker_signal_passed",
            reasons=(),
            inputs=inputs,
            execution_eligible=False,
        )


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


class WorkerSignalFederation:
    MODEL_SPECS = (
        ("worker_signal_sma_v1", "legacy_sma_crossover_worker", "trend", SMAWorker()),
        ("worker_signal_rsi_v1", "legacy_rsi_reversion_worker", "mean_reversion", RSIWorker()),
        ("worker_signal_rsi2_v1", "legacy_connors_rsi2_worker", "mean_reversion", RSI2Worker()),
        ("worker_signal_breakout_v1", "legacy_breakout_worker", "breakout", BreakoutWorker()),
        ("worker_signal_momentum_v1", "legacy_momentum_worker", "momentum", MomentumWorker()),
        ("worker_signal_bollinger_v1", "legacy_bollinger_reversion_worker", "mean_reversion", BollingerWorker()),
        ("worker_signal_supertrend_v1", "legacy_supertrend_worker", "trend", SupertrendWorker()),
        ("worker_signal_vol_expansion_v1", "legacy_volatility_expansion_worker", "breakout", VolatilityExpansionWorker()),
    )

    def __init__(self, cfg: Any, cost_model: ResearchCostModel) -> None:
        self.enabled = bool(getattr(cfg, "phase2_worker_signal_federation_enabled", True))
        configured = getattr(cfg, "phase2_worker_signal_models", None) or [spec[0] for spec in self.MODEL_SPECS]
        selected = {str(item).strip() for item in configured if str(item).strip()}
        min_quality = float(
            getattr(cfg, "phase2_worker_signal_min_data_quality", getattr(cfg, "phase2_min_data_quality", 0.99)) or 0.99
        )
        edge_multiple = float(getattr(cfg, "phase2_worker_signal_minimum_edge_multiple", 1.10) or 1.10)
        min_strength = float(getattr(cfg, "phase2_worker_signal_min_strength", 0.45) or 0.45)
        score_scale = float(getattr(cfg, "phase2_worker_signal_score_scale", 1.0) or 1.0)
        settle_counterfactuals = bool(getattr(cfg, "phase2_worker_signal_settle_counterfactuals_enabled", True))
        negative_memory_enabled = bool(getattr(cfg, "phase2_worker_signal_negative_memory_enabled", True))
        negative_memory_min_samples = int(getattr(cfg, "phase2_worker_signal_negative_memory_min_samples", 3) or 3)
        negative_memory_max_mean_net_bps = float(
            getattr(cfg, "phase2_worker_signal_negative_memory_max_mean_net_bps", -5.0) or -5.0
        )
        negative_memory_min_directional_hit_rate = float(
            getattr(cfg, "phase2_worker_signal_negative_memory_min_directional_hit_rate", 0.42) or 0.42
        )
        triune_mind_enabled = bool(getattr(cfg, "phase2_worker_signal_triune_mind_enabled", True))
        triune_loki_enabled = bool(getattr(cfg, "phase2_worker_signal_triune_loki_enabled", True))
        triune_michael_min_validation_score = float(
            getattr(cfg, "phase2_worker_signal_triune_michael_min_validation_score", 0.42) or 0.42
        )
        triune_loki_veto_risk = float(getattr(cfg, "phase2_worker_signal_triune_loki_veto_risk", 0.82) or 0.82)
        triune_loki_challenge_risk = float(
            getattr(cfg, "phase2_worker_signal_triune_loki_challenge_risk", 0.45) or 0.45
        )
        self.models = tuple(
            WorkerSignalModel(
                cost_model=cost_model,
                worker=worker,
                model_id=model_id,
                hypothesis=hypothesis,
                family=family,
                min_data_quality=min_quality,
                minimum_edge_multiple=edge_multiple,
                min_strength=min_strength,
                score_scale=score_scale,
                settle_counterfactuals=settle_counterfactuals,
                negative_memory_enabled=negative_memory_enabled,
                negative_memory_min_samples=negative_memory_min_samples,
                negative_memory_max_mean_net_bps=negative_memory_max_mean_net_bps,
                negative_memory_min_directional_hit_rate=negative_memory_min_directional_hit_rate,
                triune_mind_enabled=triune_mind_enabled,
                triune_loki_enabled=triune_loki_enabled,
                triune_michael_min_validation_score=triune_michael_min_validation_score,
                triune_loki_veto_risk=triune_loki_veto_risk,
                triune_loki_challenge_risk=triune_loki_challenge_risk,
            )
            for model_id, hypothesis, family, worker in self.MODEL_SPECS
            if model_id in selected
        ) if self.enabled else ()

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(model.model_id for model in self.models)

    def manifest(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": "legacy_worker_research_forecasts_only",
            "model_count": len(self.models),
            "models": [model.descriptor.to_dict() for model in self.models],
            "authority": "none",
            "execution_wired": False,
            "orders_submitted": 0,
        }
