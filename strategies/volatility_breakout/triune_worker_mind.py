from __future__ import annotations

import math
from typing import Any, Mapping

from .cost_model import CostEstimate
from .models import FeatureVector


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _regime_hint(features: FeatureVector) -> str:
    values = features.values if isinstance(features.values, Mapping) else {}
    regime = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), Mapping) else {}
    return str(regime.get("regime_hint") or "unknown")


def _stable_pair(symbol: str) -> bool:
    parts = [part.upper() for part in str(symbol or "").replace("-", "/").split("/") if part]
    if len(parts) != 2:
        return False
    stable = {"USD", "USDT", "USDC", "DAI", "EUR"}
    return parts[0] in stable and parts[1] in stable


def _family_regime_mismatch(family: str, regime: str) -> bool:
    family = str(family or "").lower()
    regime = str(regime or "unknown")
    if family in {"breakout", "momentum", "trend"}:
        return regime not in {"trend_expansion", "balanced_transition"}
    if family == "mean_reversion":
        return regime not in {"stretch_exhaustion", "quiet_range", "balanced_transition"}
    return False


class TriuneWorkerMind:
    """Metatron/Michael/Loki-style governance for research-only worker signals.

    This is deterministic and local. It borrows the Triune pattern from the
    Metatron stack, but its authority is limited to Phase-2 forecast admission.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        loki_enabled: bool = True,
        michael_min_validation_score: float = 0.42,
        loki_veto_risk: float = 0.82,
        loki_challenge_risk: float = 0.45,
    ) -> None:
        self.enabled = bool(enabled)
        self.loki_enabled = bool(loki_enabled)
        self.michael_min_validation_score = _clip(michael_min_validation_score)
        self.loki_veto_risk = _clip(loki_veto_risk)
        self.loki_challenge_risk = _clip(loki_challenge_risk)

    def assess(
        self,
        *,
        features: FeatureVector,
        worker_id: str,
        model_id: str,
        family: str,
        direction: str,
        horizon_seconds: int,
        strength: float,
        cost: CostEstimate,
        expected_move_bps: float,
        expected_net_bps: float,
        edge_multiple: float,
        worker_memory: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "schema": "hivenance_triune_worker_mind_v1",
                "enabled": False,
                "final_verdict": "ALLOW_RESEARCH",
                "authority": "research_admission_only",
                "execution_authority": "none",
            }
        regime = _regime_hint(features)
        michael = self._michael(
            features=features,
            family=family,
            strength=strength,
            cost=cost,
            expected_move_bps=expected_move_bps,
            edge_multiple=edge_multiple,
            worker_memory=worker_memory or {},
        )
        loki = self._loki(
            features=features,
            family=family,
            direction=direction,
            horizon_seconds=horizon_seconds,
            cost=cost,
            expected_move_bps=expected_move_bps,
            expected_net_bps=expected_net_bps,
            edge_multiple=edge_multiple,
            worker_memory=worker_memory or {},
            regime=regime,
        ) if self.loki_enabled else {"status": "aligned", "risk_score": 0.0, "challenges": []}
        metatron = self._metatron(
            michael_score=float(michael.get("validation_score") or 0.0),
            loki_risk=float(loki.get("risk_score") or 0.0),
            expected_net_bps=expected_net_bps,
            edge_multiple=edge_multiple,
        )
        final_verdict = "ALLOW_RESEARCH"
        reasons: list[str] = []
        if float(michael.get("validation_score") or 0.0) < self.michael_min_validation_score:
            final_verdict = "VETO"
            reasons.append("michael_validation_below_floor")
        if str(loki.get("status") or "") == "vetoed" or float(loki.get("risk_score") or 0.0) >= self.loki_veto_risk:
            final_verdict = "VETO"
            reasons.append("loki_veto")
        elif final_verdict == "ALLOW_RESEARCH" and (
            str(loki.get("status") or "") == "challenged"
            or float(loki.get("risk_score") or 0.0) >= self.loki_challenge_risk
        ):
            final_verdict = "CHALLENGE_RESEARCH"
            reasons.append("loki_challenge")
        return {
            "schema": "hivenance_triune_worker_mind_v1",
            "enabled": True,
            "worker_id": worker_id,
            "model_id": model_id,
            "family": family,
            "direction": direction,
            "horizon_seconds": int(horizon_seconds),
            "regime_hint": regime,
            "metatron": metatron,
            "michael": michael,
            "loki": loki,
            "final_verdict": final_verdict,
            "reasons": reasons,
            "authority": "research_admission_only",
            "execution_authority": "none",
            "orders_submitted": 0,
        }

    @staticmethod
    def challenged_projection_multiplier(assessment: Mapping[str, Any]) -> float:
        loki = assessment.get("loki") if isinstance(assessment.get("loki"), Mapping) else {}
        risk = _clip(_num(loki.get("risk_score"), 0.0))
        if str(assessment.get("final_verdict") or "") == "CHALLENGE_RESEARCH":
            return round(max(0.35, 1.0 - 0.45 * risk), 6)
        return 1.0

    def _michael(
        self,
        *,
        features: FeatureVector,
        family: str,
        strength: float,
        cost: CostEstimate,
        expected_move_bps: float,
        edge_multiple: float,
        worker_memory: Mapping[str, Any],
    ) -> dict[str, Any]:
        liquidity_score = _clip(math.log10(max(1.0, _num(features.depth_usd_25bps))) / 7.0)
        spread_score = _clip(1.0 - (_num(features.spread_bps, 999.0) / 80.0))
        freshness_score = _clip(1.0 - (_num(features.freshness_sec, 999.0) / 60.0))
        quality_score = _clip(_num(features.data_quality))
        cost_survival = _clip(edge_multiple / 2.0)
        strength_score = _clip(strength)
        memory_samples = int(_num(worker_memory.get("samples"), 0.0)) if isinstance(worker_memory, Mapping) else 0
        memory_net = worker_memory.get("mean_net_bps") if isinstance(worker_memory, Mapping) else None
        memory_score = 0.5
        if memory_samples > 0 and memory_net is not None:
            memory_score = _clip(0.5 + (_num(memory_net) / 50.0))
        validation_score = (
            0.18 * quality_score
            + 0.14 * freshness_score
            + 0.16 * liquidity_score
            + 0.14 * spread_score
            + 0.18 * cost_survival
            + 0.12 * strength_score
            + 0.08 * memory_score
        )
        return {
            "role": "MICHAEL_VALIDATOR",
            "validation_score": round(_clip(validation_score), 6),
            "components": {
                "data_quality": round(quality_score, 6),
                "freshness": round(freshness_score, 6),
                "liquidity": round(liquidity_score, 6),
                "spread": round(spread_score, 6),
                "cost_survival": round(cost_survival, 6),
                "signal_strength": round(strength_score, 6),
                "memory": round(memory_score, 6),
            },
            "family": family,
            "expected_move_bps": round(float(expected_move_bps), 6),
            "cost_bps": round(float(cost.total_bps), 6),
            "edge_multiple": round(float(edge_multiple), 6),
        }

    def _loki(
        self,
        *,
        features: FeatureVector,
        family: str,
        direction: str,
        horizon_seconds: int,
        cost: CostEstimate,
        expected_move_bps: float,
        expected_net_bps: float,
        edge_multiple: float,
        worker_memory: Mapping[str, Any],
        regime: str,
    ) -> dict[str, Any]:
        challenges: list[dict[str, Any]] = []
        spread = _num(features.spread_bps, 0.0)
        atr_bps = _num(features.atr_pct, 0.0) * 10_000.0
        recent_move_bps = abs(_num(features.return_5, 0.0)) * 10_000.0
        memory_samples = int(_num(worker_memory.get("samples"), 0.0)) if isinstance(worker_memory, Mapping) else 0
        memory_net = worker_memory.get("mean_net_bps") if isinstance(worker_memory, Mapping) else None
        hit_rate = worker_memory.get("directional_hit_rate") if isinstance(worker_memory, Mapping) else None

        def add(name: str, risk: float, note: str) -> None:
            challenges.append({"challenge": name, "risk": round(_clip(risk), 6), "note": note})

        if expected_move_bps <= max(1.0, float(cost.total_bps) * 0.60):
            add("cost_dominates_projection", 0.86, "projected move is too small relative to fee/spread/impact")
        elif expected_net_bps <= 0:
            add("negative_expected_net_after_costs", 0.62, "forecast is direction-only until it beats friction")
        if _stable_pair(features.symbol) and expected_move_bps <= float(cost.total_bps) * 1.20:
            add("stable_pair_spread_trap", 0.90, "stable pairs often generate fake signals eaten by spread/fees")
        if spread >= max(20.0, expected_move_bps * 0.35):
            add("spread_too_wide_for_signal", 0.65, "entry spread consumes too much projected edge")
        if recent_move_bps < float(cost.total_bps) * 0.25 and atr_bps < float(cost.total_bps) * 0.75:
            add("micro_move_noise_trap", 0.58, "recent and ATR movement are too small for the cost hurdle")
        if _family_regime_mismatch(family, regime):
            add("worker_family_regime_mismatch", 0.55, "worker family is firing outside its preferred regime")
        if memory_samples >= 3 and memory_net is not None and _num(memory_net) <= -5.0:
            risk = 0.72
            if hit_rate is not None and _num(hit_rate) < 0.42:
                risk = 0.88
            add("negative_worker_memory", risk, "recent settled slice has been losing")

        risk_score = max([float(item["risk"]) for item in challenges] + [0.0])
        status = "aligned"
        if risk_score >= self.loki_veto_risk:
            status = "vetoed"
        elif risk_score >= self.loki_challenge_risk:
            status = "challenged"
        return {
            "role": "LOKI_ADVERSARY",
            "status": status,
            "risk_score": round(risk_score, 6),
            "challenges": challenges[:8],
            "alternative_hypotheses": [
                "worker_is_detecting_noise_not_edge",
                "spread_fee_drag_exceeds_directional_information",
                "regime_or_microstructure_shift_invalidates_indicator",
            ][: 1 + min(2, len(challenges))],
            "horizon_seconds": int(horizon_seconds),
            "authority": "dissent_only",
        }

    @staticmethod
    def _metatron(
        *,
        michael_score: float,
        loki_risk: float,
        expected_net_bps: float,
        edge_multiple: float,
    ) -> dict[str, Any]:
        edge_score = _clip(0.5 + (float(expected_net_bps) / 50.0))
        cost_score = _clip(float(edge_multiple) / 2.0)
        harmony = _clip((0.45 * michael_score) + (0.25 * edge_score) + (0.20 * cost_score) + (0.10 * (1.0 - loki_risk)))
        return {
            "role": "METATRON_SYNTHESIS",
            "harmony_score": round(harmony, 6),
            "edge_score": round(edge_score, 6),
            "cost_score": round(cost_score, 6),
            "loki_risk_absorbed": round(_clip(loki_risk), 6),
            "policy_tier_suggestion": "strict" if harmony < 0.55 else "standard",
        }
