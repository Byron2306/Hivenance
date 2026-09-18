from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else float(default)
    except (TypeError, ValueError):
        return float(default)


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SystemLineage:
    system: str
    capability: str
    source_path: str
    source_digest: str | None
    available: bool
    authority: str = "design_evidence_only"


@dataclass(frozen=True)
class PolyphonicVoice:
    voice: str
    role: str
    signed_score: float
    confidence: float
    rationale: str


@dataclass(frozen=True)
class AdversarialChallenge:
    challenge_id: str
    passed: bool
    observed: float
    threshold: float
    refusal_reason: str


class AdvancedSystemsMarketSynthesizer:
    """Bounded market-research synthesis derived from the owner's major systems.

    The external projects remain design and lineage authorities only. This class
    performs a deterministic, local reproduction against Hivenance feature
    vectors and never imports their service runtimes or grants order authority.
    """

    SOURCE_SPECS = (
        (
            "vns",
            "independent_sensor_quality",
            "metatron",
            "backend/services/vns.py",
        ),
        (
            "cce",
            "temporal_correlation_and_persistence",
            "metatron",
            "backend/services/cognition_engine.py",
        ),
        (
            "triune",
            "proposal_rank_dissent_adjudication",
            "metatron",
            "backend/services/triune_orchestrator.py",
        ),
        (
            "polyphonic_resonance",
            "multi_voice_coherence_with_preserved_dissent",
            "metatron",
            "backend/services/harmonic_inference.py",
        ),
        (
            "seraph",
            "adversarial_challenge_curriculum",
            "beast",
            "app/kernel/dai/seraph_bridge.py",
        ),
        (
            "sophia",
            "adaptive_evidence_curriculum",
            "integritas",
            "arda_os/backend/services/sophia_curriculum_gate.py",
        ),
        (
            "mandos",
            "bounded_memory_and_decision_lineage",
            "metatron",
            "backend/valinor/mandos_ledger.py",
        ),
    )

    DEFAULT_ROOTS = {
        "metatron": "/home/byron/Downloads/Metatron-triune-outbound-gate",
        "beast": "/home/byron/EdgeK-BEAST",
        "integritas": "/home/byron/Integritas-Mechanicus",
    }

    def __init__(
        self,
        *,
        source_roots: Mapping[str, str] | None = None,
        minimum_edge_multiple: float = 1.1,
    ) -> None:
        configured = dict(self.DEFAULT_ROOTS)
        configured.update({str(k): str(v) for k, v in (source_roots or {}).items() if v})
        for key in tuple(configured):
            configured[key] = os.path.expanduser(configured[key])
        self.minimum_edge_multiple = max(1.0, float(minimum_edge_multiple))
        self.lineage = tuple(self._lineage(spec, configured) for spec in self.SOURCE_SPECS)

    @staticmethod
    def _lineage(spec: tuple[str, str, str, str], roots: Mapping[str, str]) -> SystemLineage:
        system, capability, root_name, relative_path = spec
        source = Path(roots.get(root_name, "")) / relative_path
        try:
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            available = source.is_file()
        except OSError:
            digest = None
            available = False
        return SystemLineage(
            system=system,
            capability=capability,
            source_path=str(source),
            source_digest=digest,
            available=available,
        )

    @property
    def source_manifest(self) -> dict[str, Any]:
        available = sum(1 for row in self.lineage if row.available)
        return {
            "mode": "deterministic_local_adapter_with_source_fingerprints",
            "available": available,
            "total": len(self.lineage),
            "coverage": round(available / max(1, len(self.lineage)), 6),
            "systems": [asdict(row) for row in self.lineage],
            "external_services_started": 0,
            "external_mutations": 0,
            "execution_authority": "none",
        }

    def synthesize(self, features: Any, cost: Any, *, horizon_seconds: int) -> dict[str, Any]:
        values = features.values if isinstance(getattr(features, "values", None), Mapping) else {}
        regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), Mapping) else {}
        regime_hint = str(regime_inputs.get("regime_hint") or "unknown")
        regime_confidence = _clip(_safe_float(regime_inputs.get("confidence")))

        sensor = self._vns_sensor_receipt(features)
        voices = self._polyphonic_voices(features)
        polyphonic = self._polyphonic_receipt(voices)
        cognition = self._cce_receipt(features, voices)
        curriculum = self._sophia_curriculum(values)

        direction_sign = int(polyphonic["direction_sign"])
        directional_strength = _safe_float(polyphonic["directional_strength"])
        horizon_scale = max(0.75, min(2.2, math.sqrt(max(60, int(horizon_seconds)) / 300.0)))
        atr_bps = max(
            1.0,
            _safe_float(getattr(features, "atr_pct", None), _safe_float(getattr(features, "realized_volatility_fast", 0.0)))
            * 10_000.0,
        )
        composite_confidence = _clip(
            0.30 * _safe_float(sensor["quality"])
            + 0.32 * _safe_float(polyphonic["resonance"])
            + 0.23 * _safe_float(cognition["persistence"])
            + 0.15 * regime_confidence
        )
        expected_move_bps = atr_bps * horizon_scale * (0.24 + 0.72 * directional_strength) * (
            0.60 + 0.40 * composite_confidence
        )

        triune = self._triune_deliberation(
            direction_sign=direction_sign,
            expected_move_bps=expected_move_bps,
            cost_bps=_safe_float(getattr(cost, "total_bps", 0.0)),
            sensor=sensor,
            polyphonic=polyphonic,
            cognition=cognition,
            regime_hint=regime_hint,
            regime_confidence=regime_confidence,
        )
        challenges = self._seraph_challenges(
            expected_move_bps=expected_move_bps,
            cost_bps=_safe_float(getattr(cost, "total_bps", 0.0)),
            sensor=sensor,
            polyphonic=polyphonic,
            cognition=cognition,
            regime_confidence=regime_confidence,
            direction_sign=direction_sign,
            curriculum_stage=int(curriculum["stage"]),
        )
        required_ids = set(curriculum["required_challenges"])
        failed = [row for row in challenges if row.challenge_id in required_ids and not row.passed]
        decision = "ACCEPT_RESEARCH_PROPOSAL" if not failed else "REFUSE_RESEARCH_PROPOSAL"
        refusal_reasons = tuple(row.refusal_reason for row in failed)

        chain_payloads: list[dict[str, Any]] = [
            {"stage": "source_lineage", "payload": self.source_manifest},
            {"stage": "vns", "payload": sensor},
            {"stage": "polyphonic", "payload": polyphonic},
            {"stage": "cce", "payload": cognition},
            {"stage": "sophia", "payload": curriculum},
            {"stage": "triune", "payload": triune},
            {"stage": "seraph", "payload": [asdict(row) for row in challenges]},
        ]
        prior_digest = "GENESIS"
        ledger = []
        for sequence, item in enumerate(chain_payloads, start=1):
            digest = _canonical_digest({"sequence": sequence, "prior": prior_digest, **item})
            ledger.append({"sequence": sequence, "prior_digest": prior_digest, "entry_digest": digest, **item})
            prior_digest = digest
        decision_digest = _canonical_digest({
            "prior_digest": prior_digest,
            "decision": decision,
            "refusal_reasons": refusal_reasons,
            "symbol": features.symbol,
            "timestamp_ms": features.timestamp_ms,
            "horizon_seconds": int(horizon_seconds),
        })

        return {
            "schema": "hivenance_advanced_systems_synthesis_receipt_v1",
            "symbol": features.symbol,
            "timestamp_ms": features.timestamp_ms,
            "horizon_seconds": int(horizon_seconds),
            "source_manifest": self.source_manifest,
            "vns_sensor": sensor,
            "polyphonic_resonance": polyphonic,
            "cce_cognition": cognition,
            "sophia_curriculum": curriculum,
            "triune_deliberation": triune,
            "seraph_challenges": [asdict(row) for row in challenges],
            "mandos_ledger": {
                "chain": ledger,
                "chain_head": prior_digest,
                "decision_digest": decision_digest,
                "decision": decision,
                "refusal_reasons": refusal_reasons,
                "authority_ceiling": "research_proposal_only",
            },
            "direction_sign": direction_sign,
            "score": round(composite_confidence * directional_strength, 6),
            "expected_move_bps": round(expected_move_bps, 6),
            "accepted": decision == "ACCEPT_RESEARCH_PROPOSAL",
            "refusal_reasons": refusal_reasons,
            "execution_eligible": False,
            "orders_submitted": 0,
        }

    @staticmethod
    def _vns_sensor_receipt(features: Any) -> dict[str, Any]:
        freshness = 1.0 - _clip(_safe_float(getattr(features, "freshness_sec", 180.0), 180.0) / 180.0)
        continuity = _clip(_safe_float(getattr(features, "continuity_ratio", 0.0)))
        quality = _clip(_safe_float(getattr(features, "data_quality", 0.0)))
        spread_health = 1.0 - _clip(_safe_float(getattr(features, "spread_bps", 100.0), 100.0) / 50.0)
        depth = max(0.0, _safe_float(getattr(features, "depth_usd_25bps", 0.0)))
        depth_health = _clip(math.log10(depth + 1.0) / 6.0)
        sensor_quality = _clip(
            0.30 * quality + 0.22 * freshness + 0.20 * continuity + 0.14 * spread_health + 0.14 * depth_health
        )
        return {
            "schema": "hivenance_vns_market_sensor_receipt_v1",
            "quality": round(sensor_quality, 6),
            "components": {
                "data_quality": round(quality, 6),
                "freshness": round(freshness, 6),
                "continuity": round(continuity, 6),
                "spread_health": round(spread_health, 6),
                "depth_health": round(depth_health, 6),
            },
            "independent_truth_claim": "observation_quality_only",
            "authority": "sensor_evidence_only",
        }

    @staticmethod
    def _polyphonic_voices(features: Any) -> tuple[PolyphonicVoice, ...]:
        return_5 = math.tanh(_safe_float(getattr(features, "return_5", 0.0)) * 180.0)
        momentum = 0.72 * math.tanh(_safe_float(getattr(features, "return_zscore", 0.0)) * 0.65) + 0.28 * return_5
        trend = math.tanh(_safe_float(getattr(features, "trend_slope", 0.0)) * 4_000.0)
        flow = 0.65 * _safe_float(getattr(features, "book_imbalance", 0.0)) + 0.35 * _safe_float(
            getattr(features, "order_flow_imbalance", 0.0)
        )
        structure = (_safe_float(getattr(features, "range_position", 0.5), 0.5) - 0.5) * 2.0
        reversion = -math.tanh(_safe_float(getattr(features, "price_zscore", 0.0)) * 0.55)
        participation = _clip(0.5 + 0.22 * _safe_float(getattr(features, "volume_zscore", 0.0)))
        return (
            PolyphonicVoice("momentum", "lead_proposal", round(momentum, 6), participation, "return persistence"),
            PolyphonicVoice("trend", "structural_companion", round(trend, 6), 0.90, "slope direction"),
            PolyphonicVoice("order_flow", "microstructure_witness", round(flow, 6), 0.78, "book and flow balance"),
            PolyphonicVoice("range_structure", "regime_witness", round(structure, 6), 0.68, "location within recent range"),
            PolyphonicVoice("mean_reversion", "loki_dissent", round(reversion, 6), 0.62, "counter-thesis against stretched price"),
        )

    @staticmethod
    def _polyphonic_receipt(voices: Iterable[PolyphonicVoice]) -> dict[str, Any]:
        rows = tuple(voices)
        weighted = [row.signed_score * row.confidence for row in rows]
        consensus = sum(weighted) / max(0.000001, sum(row.confidence for row in rows))
        direction_sign = 1 if consensus > 0 else -1 if consensus < 0 else 0
        total_energy = sum(abs(value) for value in weighted)
        aligned_energy = sum(abs(value) for value in weighted if value * direction_sign > 0)
        opposing_energy = sum(abs(value) for value in weighted if value * direction_sign < 0)
        resonance = aligned_energy / max(0.000001, total_energy)
        discord = opposing_energy / max(0.000001, total_energy)
        return {
            "schema": "hivenance_polyphonic_market_resonance_v1",
            "voices": [asdict(row) for row in rows],
            "consensus": round(consensus, 6),
            "direction_sign": direction_sign,
            "directional_strength": round(_clip(abs(consensus) * 1.8), 6),
            "resonance": round(_clip(resonance), 6),
            "discord": round(_clip(discord), 6),
            "dissent_preserved": any(row.role == "loki_dissent" for row in rows),
            "authority": "coherence_assessment_only",
        }

    @staticmethod
    def _cce_receipt(features: Any, voices: Iterable[PolyphonicVoice]) -> dict[str, Any]:
        directional = [row.signed_score for row in voices if row.role != "loki_dissent" and abs(row.signed_score) >= 0.05]
        signs = [1 if value > 0 else -1 for value in directional]
        dominant = 1 if sum(signs) > 0 else -1 if sum(signs) < 0 else 0
        goal_persistence = sum(1 for sign in signs if sign == dominant) / max(1, len(signs))
        switches = sum(1 for left, right in zip(signs, signs[1:]) if left != right)
        switch_stability = 1.0 - (switches / max(1, len(signs) - 1))
        momentum_consistency = _clip(_safe_float(getattr(features, "momentum_consistency", 0.0)))
        participation = _clip(0.5 + 0.20 * _safe_float(getattr(features, "volume_zscore", 0.0)))
        persistence = _clip(
            0.36 * goal_persistence + 0.24 * switch_stability + 0.28 * momentum_consistency + 0.12 * participation
        )
        return {
            "schema": "hivenance_cce_market_cognition_receipt_v1",
            "persistence": round(persistence, 6),
            "goal_persistence": round(goal_persistence, 6),
            "cross_feature_switch_stability": round(switch_stability, 6),
            "momentum_consistency": round(momentum_consistency, 6),
            "voice_count": len(signs),
            "authority": "correlation_assessment_only",
        }

    @staticmethod
    def _sophia_curriculum(values: Mapping[str, Any]) -> dict[str, Any]:
        memory = values.get("phase2_crystal_memory") if isinstance(values.get("phase2_crystal_memory"), Mapping) else {}
        encounters = int(_safe_float(memory.get("positive_recent"))) + int(_safe_float(memory.get("negative_recent")))
        if encounters < 5:
            stage = 1
            name = "foundational_truth"
            required = ("direction_present", "sensor_quality", "polyphonic_resonance", "cost_stress")
        elif encounters < 15:
            stage = 2
            name = "correlated_reasoning"
            required = ("direction_present", "sensor_quality", "polyphonic_resonance", "cost_stress", "regime_grounding", "cce_persistence")
        elif encounters < 30:
            stage = 3
            name = "adversarial_transfer"
            required = ("direction_present", "sensor_quality", "polyphonic_resonance", "cost_stress", "regime_grounding", "cce_persistence", "dissent_bound")
        else:
            stage = 4
            name = "robust_generalization"
            required = ("direction_present", "sensor_quality", "polyphonic_resonance", "cost_stress", "regime_grounding", "cce_persistence", "dissent_bound", "volatility_haircut")
        return {
            "schema": "hivenance_sophia_research_curriculum_v1",
            "stage": stage,
            "stage_name": name,
            "prior_encounters": encounters,
            "required_challenges": required,
            "rule": "difficulty increases with reusable slice evidence; promotion remains external",
            "authority": "experiment_curriculum_only",
        }

    def _seraph_challenges(
        self,
        *,
        expected_move_bps: float,
        cost_bps: float,
        sensor: Mapping[str, Any],
        polyphonic: Mapping[str, Any],
        cognition: Mapping[str, Any],
        regime_confidence: float,
        direction_sign: int,
        curriculum_stage: int,
    ) -> tuple[AdversarialChallenge, ...]:
        stress_multiple = max(1.5, self.minimum_edge_multiple)
        observed = {
            "direction_present": float(abs(direction_sign)),
            "sensor_quality": _safe_float(sensor.get("quality")),
            "polyphonic_resonance": _safe_float(polyphonic.get("resonance")),
            "cost_stress": expected_move_bps / max(0.000001, cost_bps),
            "regime_grounding": regime_confidence,
            "cce_persistence": _safe_float(cognition.get("persistence")),
            "dissent_bound": 1.0 - _safe_float(polyphonic.get("discord")),
            "volatility_haircut": (expected_move_bps * 0.65) / max(0.000001, cost_bps),
        }
        thresholds = {
            "direction_present": 1.0,
            "sensor_quality": 0.72,
            "polyphonic_resonance": 0.62,
            "cost_stress": stress_multiple,
            "regime_grounding": 0.35,
            "cce_persistence": 0.55,
            "dissent_bound": 0.58,
            "volatility_haircut": stress_multiple,
        }
        return tuple(
            AdversarialChallenge(
                challenge_id=challenge_id,
                passed=value >= thresholds[challenge_id],
                observed=round(value, 6),
                threshold=round(thresholds[challenge_id], 6),
                refusal_reason=f"seraph_{challenge_id}_refused_stage_{curriculum_stage}",
            )
            for challenge_id, value in observed.items()
        )

    @staticmethod
    def _triune_deliberation(
        *,
        direction_sign: int,
        expected_move_bps: float,
        cost_bps: float,
        sensor: Mapping[str, Any],
        polyphonic: Mapping[str, Any],
        cognition: Mapping[str, Any],
        regime_hint: str,
        regime_confidence: float,
    ) -> dict[str, Any]:
        edge_multiple = expected_move_bps / max(0.000001, cost_bps)
        dissent = _safe_float(polyphonic.get("discord"))
        return {
            "schema": "hivenance_triune_market_deliberation_v1",
            "metatron": {
                "role": "world_state_interpretation",
                "proposed_direction": "UP" if direction_sign > 0 else "DOWN" if direction_sign < 0 else "ABSTAIN",
                "regime_hint": regime_hint,
                "regime_confidence": round(regime_confidence, 6),
            },
            "michael": {
                "role": "candidate_ranking",
                "robust_utility": round(_clip((edge_multiple / 3.0) * _safe_float(sensor.get("quality"))), 6),
                "edge_multiple": round(edge_multiple, 6),
            },
            "loki": {
                "role": "mandatory_dissent",
                "discord": round(dissent, 6),
                "challenge": "mean_reversion_and_cross_feature_contradiction",
            },
            "adjudicator": {
                "role": "proposal_only_synthesis",
                "coherence": round(_safe_float(polyphonic.get("resonance")), 6),
                "persistence": round(_safe_float(cognition.get("persistence")), 6),
                "execution_authority": "none",
            },
        }
