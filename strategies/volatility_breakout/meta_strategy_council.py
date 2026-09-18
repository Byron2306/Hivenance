from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Iterable, Mapping

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


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MetaStrategyCouncil:
    """Ainur-inspired deterministic council for strategy-family routing.

    This layer does not forecast and cannot execute. It witnesses whether a
    strategy family deserves a voice in the current market context.
    """

    ALL_FAMILIES = ("trend", "momentum", "breakout", "mean_reversion")

    def __init__(
        self,
        *,
        enabled: bool = True,
        min_harmony_index: float = 0.60,
        min_regime_confidence: float = 0.35,
        stale_after_sec: float = 45.0,
        min_continuity: float = 0.92,
        negative_memory_mean_net_bps: float = -5.0,
        negative_memory_min_samples: int = 3,
    ) -> None:
        self.enabled = bool(enabled)
        self.min_harmony_index = _clip(min_harmony_index)
        self.min_regime_confidence = _clip(min_regime_confidence)
        self.stale_after_sec = max(1.0, float(stale_after_sec))
        self.min_continuity = _clip(min_continuity)
        self.negative_memory_mean_net_bps = float(negative_memory_mean_net_bps)
        self.negative_memory_min_samples = max(1, int(negative_memory_min_samples))

    def consult(
        self,
        *,
        features: FeatureVector,
        cost: CostEstimate,
        available_families: Iterable[str] = ALL_FAMILIES,
    ) -> dict[str, Any]:
        available = tuple(dict.fromkeys(str(item) for item in available_families if str(item)))
        if not self.enabled:
            return {
                "schema": "hivenance_meta_strategy_council_v1",
                "enabled": False,
                "allowed_families": list(available),
                "blocked_families": [],
                "canonical_runtime_state": "harmonic",
                "authority": "research_routing_only",
                "execution_authority": "none",
                "orders_submitted": 0,
            }

        context = self._context(features=features, cost=cost, available_families=available)
        reports = [
            self._manwe_cadence(context),
            self._varda_truth(context),
            self._vaire_regime(context),
            self._mandos_memory(context),
            self._ulmo_liquidity(context),
        ]
        synthesis = self._aule_synthesis(context, reports)
        reports.append(synthesis)
        lawful_count = sum(1 for item in reports if item["judgment"] == "LAWFUL")
        dissonant_count = sum(1 for item in reports if item["judgment"] == "DISSONANT" or item.get("dissonance_detected"))
        harmony_index = _clip(1.0 - dissonant_count / max(len(reports), 1))
        consensus_reached = lawful_count >= math.ceil(len(reports) * 0.67) and harmony_index >= self.min_harmony_index
        allowed = list(synthesis["allowed_families"]) if consensus_reached else []
        blocked = sorted(set(available).difference(allowed).union(synthesis.get("blocked_families") or []))
        if not allowed and synthesis["judgment"] != "DISSONANT":
            state = "muted"
        elif not consensus_reached:
            state = "dissonant"
        elif harmony_index < 0.85:
            state = "strained"
        else:
            state = "harmonic"
        return {
            "schema": "hivenance_meta_strategy_council_v1",
            "source_pattern": "arda_ainur_witness_council",
            "enabled": True,
            "lane": context["regime_hint"],
            "harmony_index": round(harmony_index, 6),
            "consensus_reached": consensus_reached,
            "lawful_count": lawful_count,
            "total_witnesses": len(reports),
            "canonical_runtime_state": state,
            "witness_sequence": [item["witness"] for item in reports],
            "resonance_summary": [
                {
                    "witness": item["witness"],
                    "domain": item["domain"],
                    "judgment": item["judgment"],
                    "state": item["state"],
                    "score": item["score"],
                    "reasons": item["reasons"],
                }
                for item in reports
            ],
            "allowed_families": allowed,
            "blocked_families": blocked,
            "strategy_budget": synthesis["strategy_budget"],
            "context_root": _stable_hash(context),
            "authority": "research_routing_only",
            "bridge_authority": "proposal_only",
            "execution_authority": "none",
            "execution_eligible": False,
            "orders_submitted": 0,
        }

    def _context(self, *, features: FeatureVector, cost: CostEstimate, available_families: tuple[str, ...]) -> dict[str, Any]:
        values = features.values if isinstance(features.values, Mapping) else {}
        regime = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), Mapping) else {}
        memory = values.get("phase2_worker_signal_memory") if isinstance(values.get("phase2_worker_signal_memory"), Mapping) else {}
        return {
            "symbol": features.symbol,
            "timestamp_ms": int(features.timestamp_ms),
            "available_families": list(available_families),
            "complete": bool(features.complete),
            "data_quality": _num(features.data_quality),
            "freshness_sec": _num(features.freshness_sec, 999.0),
            "continuity_ratio": _num(features.continuity_ratio, 0.0),
            "spread_bps": _num(features.spread_bps, 999.0),
            "depth_usd_25bps": _num(features.depth_usd_25bps, 0.0),
            "quote_volume_24h": _num(features.quote_volume_24h, 0.0),
            "volatility_expansion": _num(features.volatility_expansion, 0.0),
            "return_zscore": _num(features.return_zscore, 0.0),
            "range_position": _num(features.range_position, 0.5),
            "momentum_consistency": _num(features.momentum_consistency, 0.0),
            "atr_pct": _num(features.atr_pct or features.realized_volatility_fast, 0.0),
            "regime_hint": str(regime.get("regime_hint") or "unknown"),
            "regime_confidence": _clip(_num(regime.get("confidence"), 0.0)),
            "trend_direction": str(regime.get("trend_direction") or "unknown"),
            "liquidity_state": str(regime.get("liquidity_state") or "unknown"),
            "cost": asdict(cost),
            "worker_memory": memory,
        }

    def _report(
        self,
        *,
        witness: str,
        domain: str,
        judgment: str,
        state: str,
        score: float,
        reasons: Iterable[str],
        allowed_families: Iterable[str] = (),
        blocked_families: Iterable[str] = (),
    ) -> dict[str, Any]:
        return {
            "witness": witness,
            "domain": domain,
            "judgment": judgment,
            "state": state,
            "score": round(_clip(score), 6),
            "reasons": [str(item) for item in reasons if item],
            "allowed_families": list(dict.fromkeys(allowed_families)),
            "blocked_families": list(dict.fromkeys(blocked_families)),
            "dissonance_detected": judgment == "DISSONANT",
        }

    def _manwe_cadence(self, context: Mapping[str, Any]) -> dict[str, Any]:
        freshness = _num(context.get("freshness_sec"), 999.0)
        continuity = _num(context.get("continuity_ratio"), 0.0)
        reasons: list[str] = []
        score = 1.0
        judgment = "LAWFUL"
        state = "flowing"
        if freshness > self.stale_after_sec:
            score *= 0.35
            state = "stalled"
            judgment = "DISSONANT"
            reasons.append("market_breath_stale")
        if continuity < self.min_continuity:
            score *= 0.55
            state = "strained" if judgment != "DISSONANT" else state
            judgment = "WITHHELD" if judgment != "DISSONANT" else judgment
            reasons.append("market_cadence_discontinuous")
        return self._report(
            witness="Manwe",
            domain="market_cadence",
            judgment=judgment,
            state=state,
            score=score,
            reasons=reasons or ["fresh_continuous_observation"],
        )

    def _varda_truth(self, context: Mapping[str, Any]) -> dict[str, Any]:
        cost = context.get("cost") if isinstance(context.get("cost"), Mapping) else {}
        quality = _num(context.get("data_quality"), 0.0)
        spread = _num(context.get("spread_bps"), 999.0)
        tradable = bool(cost.get("tradable"))
        score = _clip(0.55 * quality + 0.25 * _clip(1.0 - spread / 80.0) + 0.20 * (1.0 if tradable else 0.0))
        reasons: list[str] = []
        judgment = "LAWFUL"
        state = "radiant"
        if quality < 0.99:
            judgment = "WITHHELD"
            state = "dimmed"
            reasons.append("measured_market_truth_below_quality_gate")
        if not tradable:
            judgment = "DISSONANT"
            state = "false"
            reasons.append(str(cost.get("reason") or "cost_not_tradable"))
        if spread > 60:
            judgment = "WITHHELD" if judgment == "LAWFUL" else judgment
            state = "dimmed" if state == "radiant" else state
            reasons.append("spread_truth_too_wide")
        return self._report(
            witness="Varda",
            domain="measured_truth_and_cost",
            judgment=judgment,
            state=state,
            score=score,
            reasons=reasons or ["market_truth_cost_and_spread_coherent"],
        )

    def _vaire_regime(self, context: Mapping[str, Any]) -> dict[str, Any]:
        regime = str(context.get("regime_hint") or "unknown")
        confidence = _num(context.get("regime_confidence"), 0.0)
        if regime == "trend_expansion":
            allowed = ("trend", "momentum", "breakout")
        elif regime == "balanced_transition":
            allowed = ("trend", "momentum", "breakout", "mean_reversion")
        elif regime in {"quiet_range", "stretch_exhaustion"}:
            allowed = ("mean_reversion", "trend")
        else:
            allowed = ("trend", "momentum", "breakout", "mean_reversion")
        judgment = "LAWFUL"
        state = "lawful"
        reasons = [f"regime_routes_{regime}"]
        score = max(confidence, 0.35)
        if confidence < self.min_regime_confidence:
            judgment = "WITHHELD"
            state = "strained"
            reasons.append("regime_confidence_below_meta_gate")
            score = max(0.20, confidence)
        return self._report(
            witness="Vaire",
            domain="regime_chronology",
            judgment=judgment,
            state=state,
            score=score,
            reasons=reasons,
            allowed_families=allowed,
            blocked_families=sorted(set(self.ALL_FAMILIES).difference(allowed)),
        )

    def _mandos_memory(self, context: Mapping[str, Any]) -> dict[str, Any]:
        memory = context.get("worker_memory") if isinstance(context.get("worker_memory"), Mapping) else {}
        model_memory = memory.get("model") if isinstance(memory.get("model"), Mapping) else {}
        blocked: set[str] = set()
        reasons: list[str] = []
        model_to_family = {
            "worker_signal_sma_v1": "trend",
            "worker_signal_rsi_v1": "mean_reversion",
            "worker_signal_rsi2_v1": "mean_reversion",
            "worker_signal_breakout_v1": "breakout",
            "worker_signal_momentum_v1": "momentum",
            "worker_signal_bollinger_v1": "mean_reversion",
            "worker_signal_supertrend_v1": "trend",
            "worker_signal_vol_expansion_v1": "breakout",
        }
        family_hits: dict[str, int] = {}
        for key, row in model_memory.items():
            if not isinstance(row, Mapping):
                continue
            model_id = str(key).split("|", 1)[0]
            family = model_to_family.get(model_id)
            if not family:
                continue
            samples = int(_num(row.get("samples"), 0.0))
            mean_net = row.get("mean_net_bps")
            if samples >= self.negative_memory_min_samples and mean_net is not None and _num(mean_net) <= self.negative_memory_mean_net_bps:
                family_hits[family] = family_hits.get(family, 0) + 1
        for family, count in family_hits.items():
            if count >= 2:
                blocked.add(family)
                reasons.append(f"{family}_family_recent_memory_negative")
        score = 1.0 - 0.18 * len(blocked)
        return self._report(
            witness="Mandos",
            domain="failure_memory",
            judgment="WITHHELD" if blocked else "LAWFUL",
            state="fading" if blocked else "remembered",
            score=score,
            reasons=reasons or ["no_family_memory_veto"],
            blocked_families=sorted(blocked),
        )

    def _ulmo_liquidity(self, context: Mapping[str, Any]) -> dict[str, Any]:
        depth = _num(context.get("depth_usd_25bps"), 0.0)
        spread = _num(context.get("spread_bps"), 999.0)
        expansion = _num(context.get("volatility_expansion"), 0.0)
        atr_bps = _num(context.get("atr_pct"), 0.0) * 10_000.0
        blocked: set[str] = set()
        allowed = set(self.ALL_FAMILIES)
        reasons: list[str] = []
        if depth <= 0:
            return self._report(
                witness="Ulmo",
                domain="deep_liquidity_current",
                judgment="DISSONANT",
                state="dark",
                score=0.0,
                reasons=["depth_current_missing"],
                blocked_families=self.ALL_FAMILIES,
            )
        if spread > 35:
            blocked.update({"mean_reversion", "trend"})
            reasons.append("spread_too_wide_for_small_edge_families")
        if expansion >= 1.45 and atr_bps >= 35:
            allowed = {"breakout", "momentum", "trend"}
            reasons.append("deep_current_favors_expansion_families")
        elif expansion <= 1.05:
            allowed = {"mean_reversion", "trend"}
            reasons.append("deep_current_favors_range_families")
        score = _clip(0.45 + 0.25 * min(1.0, math.log10(max(depth, 1.0)) / 7.0) + 0.20 * _clip(1.0 - spread / 80.0) + 0.10 * _clip(expansion / 2.0))
        return self._report(
            witness="Ulmo",
            domain="deep_liquidity_current",
            judgment="LAWFUL" if score >= 0.55 else "WITHHELD",
            state="clear" if score >= 0.55 else "troubled",
            score=score,
            reasons=reasons or ["deep_current_allows_balanced_family_set"],
            allowed_families=sorted(allowed),
            blocked_families=sorted(blocked),
        )

    def _aule_synthesis(self, context: Mapping[str, Any], reports: list[Mapping[str, Any]]) -> dict[str, Any]:
        available = set(context.get("available_families") or self.ALL_FAMILIES)
        allowed = set(available)
        blocked: set[str] = set()
        reasons: list[str] = []
        for report in reports:
            report_allowed = set(report.get("allowed_families") or [])
            report_blocked = set(report.get("blocked_families") or [])
            if report_allowed:
                allowed &= report_allowed
            blocked |= report_blocked
            if report.get("judgment") == "DISSONANT":
                reasons.extend(str(item) for item in report.get("reasons") or [])
        allowed -= blocked
        budget = {family: round(1.0 / max(len(allowed), 1), 6) for family in sorted(allowed)}
        score = sum(_num(report.get("score"), 0.0) for report in reports) / max(len(reports), 1)
        judgment = "LAWFUL" if allowed and score >= 0.55 and not reasons else "DISSONANT" if reasons else "WITHHELD"
        state = "harmonic" if judgment == "LAWFUL" else "vetoed" if judgment == "DISSONANT" else "withheld"
        return self._report(
            witness="Aule",
            domain="strategy_synthesis",
            judgment=judgment,
            state=state,
            score=score,
            reasons=reasons or ([f"allowed_families={','.join(sorted(allowed))}"] if allowed else ["no_strategy_family_survived"]),
            allowed_families=sorted(allowed),
            blocked_families=sorted(blocked),
        ) | {"strategy_budget": budget}
