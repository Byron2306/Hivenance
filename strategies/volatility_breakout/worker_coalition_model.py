from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
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
from .meta_strategy_council import MetaStrategyCouncil
from .models import FeatureVector, Forecast
from .triune_worker_mind import TriuneWorkerMind


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


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


class WorkerCoalitionMetaModel:
    """Aggregates legacy worker proposals into one governed research forecast.

    Individual workers are noisy scouts. This model treats them as voters, runs
    each vote through the Triune worker mind, then admits only a coalition-level
    forecast when agreement and projected edge survive costs.
    """

    model_id = "worker_coalition_meta_v1"
    hypothesis = "worker_coalition_meta"
    is_baseline = False
    WORKER_SPECS = (
        ("worker_signal_sma_v1", "legacy_sma_crossover_worker", "trend", SMAWorker()),
        ("worker_signal_rsi_v1", "legacy_rsi_reversion_worker", "mean_reversion", RSIWorker()),
        ("worker_signal_rsi2_v1", "legacy_connors_rsi2_worker", "mean_reversion", RSI2Worker()),
        ("worker_signal_breakout_v1", "legacy_breakout_worker", "breakout", BreakoutWorker()),
        ("worker_signal_momentum_v1", "legacy_momentum_worker", "momentum", MomentumWorker()),
        ("worker_signal_bollinger_v1", "legacy_bollinger_reversion_worker", "mean_reversion", BollingerWorker()),
        ("worker_signal_supertrend_v1", "legacy_supertrend_worker", "trend", SupertrendWorker()),
        ("worker_signal_vol_expansion_v1", "legacy_volatility_expansion_worker", "breakout", VolatilityExpansionWorker()),
    )
    DEFAULT_SYMBOL_CLASS_BUDGETS = {
        "stable": {
            "families": ("mean_reversion",),
            "min_voters_delta": 0,
            "min_agreement_delta": 0.08,
            "edge_multiple": 1.45,
            "note": "stable_pair_conservative_reversion_budget",
        },
        "major": {
            "families": ("trend", "breakout", "momentum", "mean_reversion"),
            "min_voters_delta": 0,
            "min_agreement_delta": 0.0,
            "edge_multiple": 1.15,
            "note": "major_liquid_broad_strategy_budget",
        },
        "core": {
            "families": ("trend", "breakout", "momentum", "mean_reversion"),
            "min_voters_delta": 0,
            "min_agreement_delta": 0.0,
            "edge_multiple": 1.15,
            "note": "core_liquid_broad_strategy_budget",
        },
        "long_tail": {
            "families": ("trend", "breakout", "momentum"),
            "min_voters_delta": 1,
            "min_agreement_delta": 0.10,
            "edge_multiple": 1.75,
            "note": "long_tail_strict_confirmation_budget",
        },
        "high_spread": {
            "families": ("mean_reversion", "trend"),
            "min_voters_delta": 1,
            "min_agreement_delta": 0.12,
            "edge_multiple": 1.90,
            "note": "high_spread_cost_survival_budget",
        },
        "hostile": {
            "families": (),
            "min_voters_delta": 99,
            "min_agreement_delta": 0.50,
            "edge_multiple": 3.00,
            "note": "hostile_liquidity_no_research_budget",
        },
        "unknown": {
            "families": ("trend", "breakout", "momentum", "mean_reversion"),
            "min_voters_delta": 1,
            "min_agreement_delta": 0.05,
            "edge_multiple": 1.45,
            "note": "unknown_symbol_class_defensive_budget",
        },
    }

    def __init__(self, cfg: Any, cost_model: ResearchCostModel) -> None:
        self.cost_model = cost_model
        self.min_data_quality = float(
            getattr(cfg, "phase2_worker_coalition_min_data_quality", getattr(cfg, "phase2_min_data_quality", 0.99)) or 0.99
        )
        self.min_voters = max(1, int(getattr(cfg, "phase2_worker_coalition_min_voters", 2) or 2))
        self.min_agreement = _clip(float(getattr(cfg, "phase2_worker_coalition_min_agreement", 0.58) or 0.58))
        self.min_strength = _clip(float(getattr(cfg, "phase2_worker_coalition_min_strength", 0.45) or 0.45))
        self.minimum_edge_multiple = max(
            1.0,
            float(getattr(cfg, "phase2_worker_coalition_minimum_edge_multiple", 1.2) or 1.2),
        )
        self.settle_counterfactuals = bool(getattr(cfg, "phase2_worker_coalition_settle_counterfactuals_enabled", True))
        self.challenged_vote_weight = _clip(
            float(getattr(cfg, "phase2_worker_coalition_challenged_vote_weight", 0.55) or 0.55),
            0.10,
            1.0,
        )
        configured = getattr(cfg, "phase2_worker_coalition_models", None) or [spec[0] for spec in self.WORKER_SPECS]
        selected = {str(item).strip() for item in configured if str(item).strip()}
        self.workers = tuple(spec for spec in self.WORKER_SPECS if spec[0] in selected)
        self.meta_strategy_council = MetaStrategyCouncil(
            enabled=bool(getattr(cfg, "phase2_meta_strategy_council_enabled", True)),
            min_harmony_index=float(getattr(cfg, "phase2_meta_strategy_min_harmony_index", 0.60) or 0.60),
            min_regime_confidence=float(getattr(cfg, "phase2_meta_strategy_min_regime_confidence", 0.35) or 0.35),
            stale_after_sec=float(getattr(cfg, "phase2_meta_strategy_stale_after_sec", 45.0) or 45.0),
            min_continuity=float(getattr(cfg, "phase2_meta_strategy_min_continuity", 0.92) or 0.92),
            negative_memory_mean_net_bps=float(
                getattr(cfg, "phase2_meta_strategy_negative_memory_mean_net_bps", -5.0) or -5.0
            ),
            negative_memory_min_samples=int(getattr(cfg, "phase2_meta_strategy_negative_memory_min_samples", 3) or 3),
        )
        self.triune_mind = TriuneWorkerMind(
            enabled=bool(getattr(cfg, "phase2_worker_coalition_triune_mind_enabled", True)),
            loki_enabled=bool(getattr(cfg, "phase2_worker_coalition_triune_loki_enabled", True)),
            michael_min_validation_score=float(
                getattr(cfg, "phase2_worker_coalition_triune_michael_min_validation_score", 0.42) or 0.42
            ),
            loki_veto_risk=float(getattr(cfg, "phase2_worker_coalition_triune_loki_veto_risk", 0.82) or 0.82),
            loki_challenge_risk=float(getattr(cfg, "phase2_worker_coalition_triune_loki_challenge_risk", 0.45) or 0.45),
        )

    @classmethod
    def _budget_name(cls, symbol_class: str) -> str:
        normalized = str(symbol_class or "unknown").lower()
        if "hostile" in normalized:
            return "hostile"
        if "stable" in normalized:
            return "stable"
        if "spread" in normalized or "illiquid" in normalized:
            return "high_spread"
        if "long" in normalized or "tail" in normalized or "new_listing" in normalized:
            return "long_tail"
        if "major" in normalized:
            return "major"
        if "core" in normalized or "liquid" in normalized:
            return "core"
        return "unknown"

    @classmethod
    def _symbol_class_budget(cls, features: FeatureVector) -> dict[str, Any]:
        values = features.values if isinstance(features.values, Mapping) else {}
        symbol_class = str(values.get("symbol_class") or "unknown")
        if symbol_class == "unknown":
            market_crystal = values.get("market_world_state_crystal") if isinstance(values.get("market_world_state_crystal"), Mapping) else {}
            symbol_class = str(market_crystal.get("symbol_class") or "unknown")
        budget_name = cls._budget_name(symbol_class)
        budget = dict(cls.DEFAULT_SYMBOL_CLASS_BUDGETS.get(budget_name, cls.DEFAULT_SYMBOL_CLASS_BUDGETS["unknown"]))
        budget["schema"] = "hivenance_worker_coalition_symbol_class_budget_v1"
        budget["budget_name"] = budget_name
        budget["symbol_class"] = symbol_class
        budget["families"] = list(budget.get("families") or [])
        budget["authority"] = "research_budget_only"
        return budget

    @staticmethod
    def _memory_key(model_id: str, horizon_seconds: int, direction: str) -> str:
        return f"{model_id}|{int(horizon_seconds)}|{direction}"

    def _series(self, features: FeatureVector) -> tuple[list[float], list[float], dict[str, Any]]:
        values = features.values if isinstance(features.values, Mapping) else {}
        series = values.get("worker_series") if isinstance(values.get("worker_series"), Mapping) else {}
        closes = [float(value) for value in (series.get("closes") or []) if _is_finite_number(value) and float(value) > 0]
        volumes = [float(value) for value in (series.get("volumes") or []) if _is_finite_number(value) and float(value) >= 0]
        if len(volumes) > len(closes):
            volumes = volumes[-len(closes):]
        return closes, volumes, dict(series)

    def _worker_memory(self, features: FeatureVector, model_id: str, horizon_seconds: int, direction: str) -> dict[str, Any]:
        values = features.values if isinstance(features.values, Mapping) else {}
        root = values.get("phase2_worker_signal_memory") if isinstance(values.get("phase2_worker_signal_memory"), Mapping) else {}
        exact = root.get("exact") if isinstance(root.get("exact"), Mapping) else {}
        model = root.get("model") if isinstance(root.get("model"), Mapping) else {}
        key = self._memory_key(model_id, horizon_seconds, direction)
        exact_match = exact.get(key) if isinstance(exact.get(key), Mapping) else {}
        if exact_match:
            return dict(exact_match)
        model_match = model.get(key) if isinstance(model.get(key), Mapping) else {}
        return dict(model_match) if model_match else {}

    def _base_inputs(
        self,
        *,
        features: FeatureVector,
        cost: CostEstimate,
        series: Mapping[str, Any],
        closes: Iterable[float],
        volumes: Iterable[float],
        voters: Iterable[Mapping[str, Any]] = (),
        coalition: Mapping[str, Any] | None = None,
        meta_strategy: Mapping[str, Any] | None = None,
        symbol_class_budget: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_closes = list(closes)
        safe_volumes = list(volumes)
        values = features.values if isinstance(features.values, Mapping) else {}
        receipt = {
            "schema": "hivenance_worker_coalition_receipt_v1",
            "model_id": self.model_id,
            "hypothesis": self.hypothesis,
            "worker_count": len(self.workers),
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
            "voters": list(voters),
            "coalition": dict(coalition or {}),
            "meta_strategy_council": dict(meta_strategy or {}),
            "symbol_class_budget": dict(symbol_class_budget or {}),
            "authority": "research_forecast_only",
            "bridge_authority": "proposal_only",
            "execution_authority": "none",
            "execution_eligible": False,
            "orders_submitted": 0,
        }
        return {
            "worker_coalition": {
                "schema": "hivenance_worker_coalition_model_v1",
                "mode": "triune_governed_worker_vote_aggregation",
                "model_id": self.model_id,
                "authority": "research_forecast_only",
                "execution_authority": "none",
            },
            "meta_strategy_council": dict(meta_strategy or {}),
            "symbol_class_budget": dict(symbol_class_budget or {}),
            "worker_coalition_receipt": receipt,
            "cost": asdict(cost),
            "feature_version": values.get("feature_version", "phase2.v1"),
            "regime_inputs": values.get("regime_inputs", {}),
            "spread_bps": features.spread_bps,
            "depth_usd_25bps": features.depth_usd_25bps,
            "atr_pct": features.atr_pct,
            "return_5": features.return_5,
            "return_zscore": features.return_zscore,
            "momentum_consistency": features.momentum_consistency,
        }

    def _abstain(
        self,
        features: FeatureVector,
        horizon_seconds: int,
        reasons: Iterable[str],
        *,
        cost: CostEstimate,
        series: Mapping[str, Any] | None = None,
        closes: Iterable[float] = (),
        volumes: Iterable[float] = (),
        voters: Iterable[Mapping[str, Any]] = (),
        coalition: Mapping[str, Any] | None = None,
        meta_strategy: Mapping[str, Any] | None = None,
        symbol_class_budget: Mapping[str, Any] | None = None,
        raw_score: float | None = None,
    ) -> Forecast:
        reason_list = tuple(str(item) for item in reasons if item)
        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=int(horizon_seconds),
            direction="ABSTAIN",
            probability_positive_net=None,
            expected_move_bps=None,
            expected_cost_bps=cost.total_bps,
            expected_net_bps=None,
            abstain=True,
            reason=reason_list[0] if reason_list else "worker_coalition_abstain",
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            raw_score=None if raw_score is None else round(float(raw_score), 6),
            uncertainty=1.0,
            calibration_state="WORKER_COALITION_COLD_START",
            feature_version="phase2.worker_coalition.v1",
            reasons=reason_list,
            inputs=self._base_inputs(
                features=features,
                cost=cost,
                series=series or {},
                closes=closes,
                volumes=volumes,
                voters=voters,
                coalition=coalition,
                meta_strategy=meta_strategy,
                symbol_class_budget=symbol_class_budget,
            ),
            execution_eligible=False,
        )

    def _counterfactual(
        self,
        features: FeatureVector,
        horizon_seconds: int,
        refusal_reason: str,
        *,
        direction: str,
        cost: CostEstimate,
        series: Mapping[str, Any],
        closes: Iterable[float],
        volumes: Iterable[float],
        voters: Iterable[Mapping[str, Any]],
        coalition: Mapping[str, Any],
        meta_strategy: Mapping[str, Any],
        symbol_class_budget: Mapping[str, Any],
        raw_score: float,
        expected_move_bps: float,
        expected_net_bps: float,
        probability_positive_net: float,
    ) -> Forecast:
        inputs = self._base_inputs(
            features=features,
            cost=cost,
            series=series,
            closes=closes,
            volumes=volumes,
            voters=voters,
            coalition=coalition,
            meta_strategy=meta_strategy,
            symbol_class_budget=symbol_class_budget,
        )
        inputs["worker_coalition_counterfactual"] = {
            "schema": "hivenance_worker_coalition_counterfactual_settlement_v1",
            "purpose": "settle_partial_or_refused_worker_coalition_without_execution_authority",
            "refusal_reason": refusal_reason,
            "authority": "research_settlement_only",
            "execution_authority": "none",
            "execution_eligible": False,
            "orders_submitted": 0,
        }
        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=int(horizon_seconds),
            direction=direction,
            probability_positive_net=round(_clip(probability_positive_net, 0.01, 0.99), 6),
            expected_move_bps=round(expected_move_bps, 6),
            expected_cost_bps=round(float(cost.total_bps), 6),
            expected_net_bps=round(expected_net_bps, 6),
            abstain=False,
            reason=f"{refusal_reason}_counterfactual",
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            raw_score=round(raw_score, 6),
            uncertainty=round(1.0 - _clip(raw_score), 6),
            calibration_state="WORKER_COALITION_COUNTERFACTUAL_REFUSED",
            feature_version="phase2.worker_coalition.v1",
            reasons=(refusal_reason, "settlement_only_refused_coalition"),
            inputs=inputs,
            execution_eligible=False,
        )

    def _projected_move(self, features: FeatureVector, strength: float, horizon_seconds: int, agreement: float) -> float:
        atr_bps = max(1.0, float(features.atr_pct or features.realized_volatility_fast or 0.0) * 10_000.0)
        recent_move_bps = abs(float(features.return_5 or 0.0)) * 10_000.0
        zscore_bps = abs(float(features.return_zscore or 0.0)) * 8.0
        raw_projection = _horizon_scale(horizon_seconds) * (
            0.48 * atr_bps + 0.34 * recent_move_bps + 0.18 * zscore_bps
        ) * (0.28 + 0.52 * min(1.0, strength) + 0.20 * min(1.0, agreement))
        return min(raw_projection, max(8.0, atr_bps * _horizon_scale(horizon_seconds) * 1.85))

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        cost = self.cost_model.estimate(features)
        closes, volumes, series = self._series(features)
        symbol_class_budget = self._symbol_class_budget(features)
        meta_strategy = self.meta_strategy_council.consult(
            features=features,
            cost=cost,
            available_families=(spec[2] for spec in self.workers),
        )
        allowed_families = {str(item) for item in (meta_strategy.get("allowed_families") or []) if str(item)}
        budget_families = {str(item) for item in (symbol_class_budget.get("families") or []) if str(item)}
        if budget_families:
            allowed_families = allowed_families.intersection(budget_families)
        else:
            allowed_families = set()
        budget_min_voters = int(self.min_voters) + int(symbol_class_budget.get("min_voters_delta") or 0)
        budget_min_agreement = _clip(float(self.min_agreement) + float(symbol_class_budget.get("min_agreement_delta") or 0.0))
        budget_edge_multiple = max(float(self.minimum_edge_multiple), float(symbol_class_budget.get("edge_multiple") or self.minimum_edge_multiple))
        reasons: list[str] = []
        if not features.complete:
            reasons.append("features_incomplete")
        if float(features.data_quality or 0.0) < self.min_data_quality:
            reasons.append("data_quality_below_gate")
        if not cost.tradable:
            reasons.append(cost.reason)
        if len(closes) < 15:
            reasons.append("worker_series_unavailable")
        if not self.workers:
            reasons.append("worker_coalition_no_configured_workers")
        if self.workers and not allowed_families:
            reasons.append("symbol_class_budget_muted_all_families")
        if reasons:
            return self._abstain(
                features,
                horizon_seconds,
                reasons,
                cost=cost,
                series=series,
                closes=closes,
                volumes=volumes,
                meta_strategy=meta_strategy,
                symbol_class_budget=symbol_class_budget,
            )

        raw_voters: list[dict[str, Any]] = []
        weighted_votes: list[float] = []
        allowed_voters = 0
        vetoes = 0
        challenges = 0
        for model_id, worker_id, family, worker in self.workers:
            if family not in allowed_families:
                raw_voters.append({
                    "model_id": model_id,
                    "worker_id": worker_id,
                    "family": family,
                    "direction": "ABSTAIN",
                    "strength": 0.0,
                    "status": "muted_by_meta_strategy_council",
                    "reason": "family_not_allowed_in_current_meta_or_symbol_class_lane",
                })
                continue
            try:
                proposal = worker.propose(closes, volumes=volumes, latest_price=float(features.price or closes[-1]))
            except Exception as exc:
                raw_voters.append({
                    "model_id": model_id,
                    "worker_id": worker_id,
                    "family": family,
                    "direction": "ABSTAIN",
                    "strength": 0.0,
                    "status": "proposal_failed",
                    "error_type": type(exc).__name__,
                })
                continue
            direction = _direction(str(proposal.get("action") or "HOLD"))
            strength = _clip(float(proposal.get("signal_strength") or 0.0), 0.0, 1.25)
            if direction == "ABSTAIN" or strength < self.min_strength:
                raw_voters.append({
                    "model_id": model_id,
                    "worker_id": worker_id,
                    "family": family,
                    "direction": direction,
                    "strength": round(strength, 6),
                    "status": "ignored",
                    "reason": "hold_or_strength_below_gate",
                    "worker_note": str(proposal.get("notes") or ""),
                })
                continue
            provisional_move = self._projected_move(features, strength, horizon_seconds, agreement=0.5)
            provisional_net = provisional_move - float(cost.total_bps)
            edge_multiple = provisional_move / max(float(cost.total_bps), 0.000001)
            memory = self._worker_memory(features, model_id, horizon_seconds, direction)
            triune = self.triune_mind.assess(
                features=features,
                worker_id=worker_id,
                model_id=model_id,
                family=family,
                direction=direction,
                horizon_seconds=int(horizon_seconds),
                strength=strength,
                cost=cost,
                expected_move_bps=provisional_move,
                expected_net_bps=provisional_net,
                edge_multiple=edge_multiple,
                worker_memory=memory,
            )
            verdict = str(triune.get("final_verdict") or "ALLOW_RESEARCH")
            if verdict == "VETO":
                vote_weight = 0.0
                vetoes += 1
            elif verdict == "CHALLENGE_RESEARCH":
                vote_weight = strength * self.challenged_vote_weight
                challenges += 1
                allowed_voters += 1
            else:
                vote_weight = strength
                allowed_voters += 1
            signed_vote = vote_weight if direction == "UP" else -vote_weight
            if vote_weight > 0:
                weighted_votes.append(signed_vote)
            raw_voters.append({
                "model_id": model_id,
                "worker_id": worker_id,
                "family": family,
                "direction": direction,
                "strength": round(strength, 6),
                "vote_weight": round(vote_weight, 6),
                "status": "admitted" if vote_weight > 0 else "vetoed",
                "worker_note": str(proposal.get("notes") or ""),
                "triune_worker_mind": triune,
            })

        total_abs_vote = sum(abs(item) for item in weighted_votes)
        net_vote = sum(weighted_votes)
        agreement = abs(net_vote) / max(total_abs_vote, 0.000001)
        mean_strength = total_abs_vote / max(allowed_voters, 1)
        direction = "UP" if net_vote > 0 else "DOWN" if net_vote < 0 else "ABSTAIN"
        coalition = {
            "allowed_voters": allowed_voters,
            "vetoes": vetoes,
            "challenges": challenges,
            "net_vote": round(net_vote, 6),
            "total_abs_vote": round(total_abs_vote, 6),
            "agreement": round(agreement, 6),
            "mean_admitted_strength": round(mean_strength, 6),
            "direction": direction,
            "symbol_class_budget": {
                "budget_name": symbol_class_budget.get("budget_name"),
                "symbol_class": symbol_class_budget.get("symbol_class"),
                "families": list(symbol_class_budget.get("families") or []),
                "min_voters": budget_min_voters,
                "min_agreement": round(budget_min_agreement, 6),
                "minimum_edge_multiple": round(budget_edge_multiple, 6),
                "note": symbol_class_budget.get("note"),
            },
        }
        raw_score = _clip(0.60 * agreement + 0.40 * mean_strength)
        early_expected_move_bps = self._projected_move(features, mean_strength, horizon_seconds, agreement=max(agreement, 0.25))
        early_expected_net_bps = early_expected_move_bps - float(cost.total_bps)
        if allowed_voters < budget_min_voters:
            if self.settle_counterfactuals and direction != "ABSTAIN" and total_abs_vote > 0:
                coalition["expected_move_bps"] = round(early_expected_move_bps, 6)
                coalition["expected_net_bps"] = round(early_expected_net_bps, 6)
                coalition["edge_multiple"] = round(early_expected_move_bps / max(float(cost.total_bps), 0.000001), 6)
                return self._counterfactual(
                    features,
                    horizon_seconds,
                    "worker_coalition_insufficient_voters",
                    direction=direction,
                    cost=cost,
                    series=series,
                    closes=closes,
                    volumes=volumes,
                    voters=raw_voters,
                    coalition=coalition,
                    meta_strategy=meta_strategy,
                    symbol_class_budget=symbol_class_budget,
                    raw_score=raw_score,
                    expected_move_bps=early_expected_move_bps,
                    expected_net_bps=early_expected_net_bps,
                    probability_positive_net=0.45 + 0.12 * raw_score,
                )
            return self._abstain(
                features,
                horizon_seconds,
                ["worker_coalition_insufficient_voters"],
                cost=cost,
                series=series,
                closes=closes,
                volumes=volumes,
                voters=raw_voters,
                coalition=coalition,
                meta_strategy=meta_strategy,
                symbol_class_budget=symbol_class_budget,
                raw_score=raw_score,
            )
        if direction == "ABSTAIN" or agreement < budget_min_agreement:
            if self.settle_counterfactuals and direction != "ABSTAIN" and total_abs_vote > 0:
                coalition["expected_move_bps"] = round(early_expected_move_bps, 6)
                coalition["expected_net_bps"] = round(early_expected_net_bps, 6)
                coalition["edge_multiple"] = round(early_expected_move_bps / max(float(cost.total_bps), 0.000001), 6)
                return self._counterfactual(
                    features,
                    horizon_seconds,
                    "worker_coalition_low_agreement",
                    direction=direction,
                    cost=cost,
                    series=series,
                    closes=closes,
                    volumes=volumes,
                    voters=raw_voters,
                    coalition=coalition,
                    meta_strategy=meta_strategy,
                    symbol_class_budget=symbol_class_budget,
                    raw_score=raw_score,
                    expected_move_bps=early_expected_move_bps,
                    expected_net_bps=early_expected_net_bps,
                    probability_positive_net=0.45 + 0.12 * raw_score,
                )
            return self._abstain(
                features,
                horizon_seconds,
                ["worker_coalition_low_agreement"],
                cost=cost,
                series=series,
                closes=closes,
                volumes=volumes,
                voters=raw_voters,
                coalition=coalition,
                meta_strategy=meta_strategy,
                symbol_class_budget=symbol_class_budget,
                raw_score=raw_score,
            )

        expected_move_bps = self._projected_move(features, mean_strength, horizon_seconds, agreement=agreement)
        expected_net_bps = expected_move_bps - float(cost.total_bps)
        edge_multiple = expected_move_bps / max(float(cost.total_bps), 0.000001)
        coalition["expected_move_bps"] = round(expected_move_bps, 6)
        coalition["expected_net_bps"] = round(expected_net_bps, 6)
        coalition["edge_multiple"] = round(edge_multiple, 6)
        if expected_net_bps <= 0 or edge_multiple < budget_edge_multiple:
            if self.settle_counterfactuals:
                return self._counterfactual(
                    features,
                    horizon_seconds,
                    "worker_coalition_cost_refused",
                    direction=direction,
                    cost=cost,
                    series=series,
                    closes=closes,
                    volumes=volumes,
                    voters=raw_voters,
                    coalition=coalition,
                    meta_strategy=meta_strategy,
                    symbol_class_budget=symbol_class_budget,
                    raw_score=raw_score,
                    expected_move_bps=expected_move_bps,
                    expected_net_bps=expected_net_bps,
                    probability_positive_net=0.48 + 0.12 * raw_score,
                )
            return self._abstain(
                features,
                horizon_seconds,
                ["worker_coalition_cost_refused"],
                cost=cost,
                series=series,
                closes=closes,
                volumes=volumes,
                voters=raw_voters,
                coalition=coalition,
                meta_strategy=meta_strategy,
                symbol_class_budget=symbol_class_budget,
                raw_score=raw_score,
            )

        veto_rate = vetoes / max(len(self.workers), 1)
        probability = _clip(0.50 + 0.18 * agreement + 0.12 * mean_strength - 0.08 * veto_rate, 0.01, 0.99)
        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=int(horizon_seconds),
            direction=direction,
            probability_positive_net=round(probability, 6),
            expected_move_bps=round(expected_move_bps, 6),
            expected_cost_bps=round(float(cost.total_bps), 6),
            expected_net_bps=round(expected_net_bps, 6),
            abstain=False,
            reason="worker_coalition_passed",
            model_id=self.model_id,
            hypothesis=self.hypothesis,
            raw_score=round(raw_score, 6),
            uncertainty=round(1.0 - raw_score, 6),
            calibration_state="WORKER_COALITION_COLD_START_PROVISIONAL",
            feature_version="phase2.worker_coalition.v1",
            reasons=(),
            inputs=self._base_inputs(
                features=features,
                cost=cost,
                series=series,
                closes=closes,
                volumes=volumes,
                voters=raw_voters,
                coalition=coalition,
                meta_strategy=meta_strategy,
                symbol_class_budget=symbol_class_budget,
            ),
            execution_eligible=False,
        )
