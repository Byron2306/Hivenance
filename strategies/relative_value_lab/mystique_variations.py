from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


SYNTHETIC_NAMESPACE = "synthetic_counterfactual"
OBSERVED_NAMESPACE = "observed_market"

VARIATION_TYPES = {
    "MUTE_LARGEST_NOTE",
    "REMOVE_DEPTH_RECOVERY",
    "INVERT_FLOW",
    "DOUBLE_SPREAD_COST",
    "BREAK_RELATIONSHIP_STABILITY",
    "REMOVE_LINEAGE",
    "MODULATE_HORIZON",
    "PERTURB_TIMING",
}


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MystiqueObservedScore:
    """Observed parent score entering the synthetic challenge chamber."""

    score_id: str
    hypothesis_id: str
    world_state_id: str
    world_state_hash: str
    observed_at_ms: int
    metrics: Mapping[str, float]
    evidence_roots: tuple[str, ...]
    lineage_roots: tuple[str, ...]
    namespace: str = OBSERVED_NAMESPACE
    authority: str = RELATIVE_VALUE_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class CounterfactualVariation:
    variation_id: str
    variation_type: str
    target: str
    strength: float
    rationale: str

    def __post_init__(self) -> None:
        if self.variation_type not in VARIATION_TYPES:
            raise ValueError("unknown_mystique_variation")
        if not 0.0 <= float(self.strength) <= 1.0:
            raise ValueError("variation_strength_out_of_range")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CounterfactualWorld:
    schema: str
    world_id: str
    parent_score_id: str
    parent_score_digest: str
    hypothesis_id: str
    world_state_id: str
    world_state_hash: str
    variation: CounterfactualVariation
    synthetic_metrics: Mapping[str, float]
    synthetic_evidence_root: str
    namespace: str = SYNTHETIC_NAMESPACE
    observed_evidence_roots: tuple[str, ...] = ()
    observed_lineage_roots: tuple[str, ...] = ()
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["variation"] = self.variation.to_dict()
        return payload


@dataclass(frozen=True)
class CounterfactualEvaluation:
    world_id: str
    variation_type: str
    support_score: float
    survived: bool
    failed_dimensions: tuple[str, ...]
    synthetic_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MystiqueFalsificationReceipt:
    schema: str
    receipt_id: str
    hypothesis_id: str
    parent_score_id: str
    parent_score_digest: str
    worlds_tested: int
    worlds_survived: int
    worlds_failed: int
    survival_rate: float
    fragility_score: float
    critical_dependencies: tuple[str, ...]
    evaluations: tuple[CounterfactualEvaluation, ...]
    synthetic_world_ids: tuple[str, ...]
    synthetic_evidence_roots: tuple[str, ...]
    contamination_guard_passed: bool
    observed_namespace_untouched: bool
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False
    prospective_evidence_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evaluations"] = tuple(item.to_dict() for item in self.evaluations)
        return payload


@dataclass(frozen=True)
class MystiqueConfig:
    # Provisional engineering defaults, not discovered market thresholds.
    survival_threshold: float = 0.55
    support_dimensions: tuple[str, ...] = (
        "motif_strength",
        "relationship_stability",
        "flow_support",
        "depth_recovery",
        "timing_coherence",
        "lineage_diversity",
        "horizon_compatibility",
        "cost_clearance",
    )


class MystiqueCounterfactualVariations:
    """Synthetic theme-and-variations falsification chamber.

    Counterfactual worlds are always synthetic, always parent-bound, and never
    become observed or prospective market evidence.
    """

    version = "hivenance.mystique_counterfactual_variations.v1"

    def __init__(self, config: MystiqueConfig | None = None) -> None:
        self.config = config or MystiqueConfig()

    @staticmethod
    def default_variations() -> tuple[CounterfactualVariation, ...]:
        return (
            CounterfactualVariation(
                "mute-largest-note",
                "MUTE_LARGEST_NOTE",
                "motif_strength",
                0.50,
                "remove the loudest contribution and test whether the motif still carries",
            ),
            CounterfactualVariation(
                "remove-depth-recovery",
                "REMOVE_DEPTH_RECOVERY",
                "depth_recovery",
                1.00,
                "remove depth recovery from the score",
            ),
            CounterfactualVariation(
                "invert-flow",
                "INVERT_FLOW",
                "flow_support",
                1.00,
                "invert flow support and test whether the interpretation depends on its sign",
            ),
            CounterfactualVariation(
                "double-spread-cost",
                "DOUBLE_SPREAD_COST",
                "cost_clearance",
                1.00,
                "double spread burden and test cost fragility",
            ),
            CounterfactualVariation(
                "break-relationship",
                "BREAK_RELATIONSHIP_STABILITY",
                "relationship_stability",
                0.75,
                "degrade pair relationship stability",
            ),
            CounterfactualVariation(
                "remove-lineage",
                "REMOVE_LINEAGE",
                "lineage_diversity",
                0.50,
                "remove one independent evidentiary voice",
            ),
            CounterfactualVariation(
                "modulate-horizon",
                "MODULATE_HORIZON",
                "horizon_compatibility",
                0.50,
                "change horizon context and test register dependence",
            ),
            CounterfactualVariation(
                "perturb-timing",
                "PERTURB_TIMING",
                "timing_coherence",
                0.50,
                "perturb event timing within a synthetic uncertainty envelope",
            ),
        )

    @staticmethod
    def _validate_observed(parent: MystiqueObservedScore) -> None:
        if parent.namespace != OBSERVED_NAMESPACE:
            raise ValueError("mystique_parent_must_be_observed_namespace")
        if not parent.world_state_hash.startswith("sha256:"):
            raise ValueError("mystique_parent_world_state_unbound")
        if any(not root.startswith("sha256:") for root in parent.evidence_roots):
            raise ValueError("mystique_parent_evidence_unbound")

    def generate_world(
        self,
        parent: MystiqueObservedScore,
        variation: CounterfactualVariation,
    ) -> CounterfactualWorld:
        self._validate_observed(parent)
        metrics = {key: float(value) for key, value in parent.metrics.items()}
        s = _clamp(variation.strength)

        if variation.variation_type == "MUTE_LARGEST_NOTE":
            metrics["motif_strength"] = _clamp(metrics.get("motif_strength", 0.0) * (1.0 - 0.5 * s))
        elif variation.variation_type == "REMOVE_DEPTH_RECOVERY":
            metrics["depth_recovery"] = _clamp(metrics.get("depth_recovery", 0.0) * (1.0 - s))
        elif variation.variation_type == "INVERT_FLOW":
            current = _clamp(metrics.get("flow_support", 0.5))
            inverted = 1.0 - current
            metrics["flow_support"] = _clamp(current * (1.0 - s) + inverted * s)
        elif variation.variation_type == "DOUBLE_SPREAD_COST":
            current = _clamp(metrics.get("cost_clearance", 0.0))
            metrics["cost_clearance"] = _clamp(current * (1.0 - 0.75 * s))
        elif variation.variation_type == "BREAK_RELATIONSHIP_STABILITY":
            metrics["relationship_stability"] = _clamp(
                metrics.get("relationship_stability", 0.0) * (1.0 - 0.75 * s)
            )
        elif variation.variation_type == "REMOVE_LINEAGE":
            current = _clamp(metrics.get("lineage_diversity", 0.0))
            lineage_count = max(1, len(parent.lineage_roots))
            decrement = s / lineage_count
            metrics["lineage_diversity"] = _clamp(current - decrement)
        elif variation.variation_type == "MODULATE_HORIZON":
            metrics["horizon_compatibility"] = _clamp(
                metrics.get("horizon_compatibility", 0.0) * (1.0 - 0.5 * s)
            )
        elif variation.variation_type == "PERTURB_TIMING":
            metrics["timing_coherence"] = _clamp(
                metrics.get("timing_coherence", 0.0) * (1.0 - 0.5 * s)
            )

        body = {
            "parent_score_digest": parent.digest,
            "variation": variation.to_dict(),
            "synthetic_metrics": metrics,
            "namespace": SYNTHETIC_NAMESPACE,
        }
        world_id = "myst_" + _digest(body).split(":", 1)[1][:24]
        synthetic_root = _digest({
            "world_id": world_id,
            "parent": parent.digest,
            "variation": variation.variation_id,
            "synthetic": True,
        })
        return CounterfactualWorld(
            schema="hivenance_mystique_counterfactual_world_v1",
            world_id=world_id,
            parent_score_id=parent.score_id,
            parent_score_digest=parent.digest,
            hypothesis_id=parent.hypothesis_id,
            world_state_id=parent.world_state_id,
            world_state_hash=parent.world_state_hash,
            variation=variation,
            synthetic_metrics=dict(sorted(metrics.items())),
            synthetic_evidence_root=synthetic_root,
            namespace=SYNTHETIC_NAMESPACE,
            observed_evidence_roots=tuple(parent.evidence_roots),
            observed_lineage_roots=tuple(parent.lineage_roots),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def evaluate_world(
        self,
        world: CounterfactualWorld,
    ) -> CounterfactualEvaluation:
        if world.namespace != SYNTHETIC_NAMESPACE:
            raise ValueError("mystique_world_not_synthetic")

        present = [
            (name, _clamp(float(world.synthetic_metrics[name])))
            for name in self.config.support_dimensions
            if name in world.synthetic_metrics
        ]
        support = statistics.fmean(value for _, value in present) if present else 0.0
        failed = tuple(
            name for name, value in present
            if value < self.config.survival_threshold
        )
        survived = (
            support >= self.config.survival_threshold
            and len(failed) <= max(1, len(present) // 3)
        )
        return CounterfactualEvaluation(
            world_id=world.world_id,
            variation_type=world.variation.variation_type,
            support_score=round(_clamp(support), 6),
            survived=bool(survived),
            failed_dimensions=tuple(sorted(failed)),
            synthetic_only=True,
        )

    def challenge(
        self,
        parent: MystiqueObservedScore,
        *,
        variations: Sequence[CounterfactualVariation] | None = None,
    ) -> MystiqueFalsificationReceipt:
        self._validate_observed(parent)
        selected = tuple(variations or self.default_variations())
        worlds = tuple(self.generate_world(parent, variation) for variation in selected)
        evaluations = tuple(self.evaluate_world(world) for world in worlds)

        survived = sum(1 for item in evaluations if item.survived)
        tested = len(evaluations)
        survival_rate = survived / tested if tested else 0.0
        fragility = 1.0 - survival_rate if tested else 0.0

        dependencies = tuple(sorted({
            item.variation_type
            for item in evaluations
            if not item.survived
        }))

        contamination_guard = all(
            world.namespace == SYNTHETIC_NAMESPACE
            and world.parent_score_digest == parent.digest
            and world.synthetic_evidence_root not in set(parent.evidence_roots)
            for world in worlds
        )

        body = {
            "parent": parent.digest,
            "evaluations": [item.to_dict() for item in evaluations],
            "synthetic_world_ids": [world.world_id for world in worlds],
        }
        return MystiqueFalsificationReceipt(
            schema="hivenance_mystique_falsification_v1",
            receipt_id="mystique_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=parent.hypothesis_id,
            parent_score_id=parent.score_id,
            parent_score_digest=parent.digest,
            worlds_tested=tested,
            worlds_survived=survived,
            worlds_failed=tested - survived,
            survival_rate=round(survival_rate, 6),
            fragility_score=round(_clamp(fragility), 6),
            critical_dependencies=dependencies,
            evaluations=evaluations,
            synthetic_world_ids=tuple(world.world_id for world in worlds),
            synthetic_evidence_roots=tuple(world.synthetic_evidence_root for world in worlds),
            contamination_guard_passed=contamination_guard,
            observed_namespace_untouched=True,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
            prospective_evidence_eligible=False,
        )
