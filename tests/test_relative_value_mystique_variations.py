from __future__ import annotations

import pytest

from strategies.relative_value_lab.mystique_variations import (
    OBSERVED_NAMESPACE,
    SYNTHETIC_NAMESPACE,
    CounterfactualVariation,
    MystiqueCounterfactualVariations,
    MystiqueObservedScore,
)


def parent(**overrides):
    metrics = {
        "motif_strength": .82,
        "relationship_stability": .80,
        "flow_support": .78,
        "depth_recovery": .76,
        "timing_coherence": .84,
        "lineage_diversity": .75,
        "horizon_compatibility": .72,
        "cost_clearance": .70,
    }
    metrics.update(overrides.pop("metrics", {}))
    return MystiqueObservedScore(
        score_id="score-1",
        hypothesis_id="motif-1",
        world_state_id="ws-1",
        world_state_hash="sha256:"+"a"*64,
        observed_at_ms=1000,
        metrics=metrics,
        evidence_roots=("sha256:"+"1"*64,"sha256:"+"2"*64),
        lineage_roots=("l1","l2","l3"),
        **overrides,
    )


def test_mystique_worlds_are_explicitly_synthetic_and_parent_bound():
    engine=MystiqueCounterfactualVariations()
    p=parent()
    world=engine.generate_world(
        p,
        CounterfactualVariation(
            "timing","PERTURB_TIMING","timing_coherence",.5,
            "synthetic timing perturbation",
        ),
    )
    assert world.namespace == SYNTHETIC_NAMESPACE
    assert world.parent_score_digest == p.digest
    assert world.synthetic_evidence_root.startswith("sha256:")
    assert world.synthetic_evidence_root not in p.evidence_roots
    assert world.execution_eligible is False
    assert world.promotion_eligible is False


def test_observed_parent_namespace_is_required():
    engine=MystiqueCounterfactualVariations()
    p=parent(namespace="synthetic_counterfactual")
    with pytest.raises(ValueError, match="observed_namespace"):
        engine.challenge(p)


def test_default_variations_cover_full_theme_and_variations_set():
    kinds={v.variation_type for v in MystiqueCounterfactualVariations.default_variations()}
    assert kinds == {
        "MUTE_LARGEST_NOTE",
        "REMOVE_DEPTH_RECOVERY",
        "INVERT_FLOW",
        "DOUBLE_SPREAD_COST",
        "BREAK_RELATIONSHIP_STABILITY",
        "REMOVE_LINEAGE",
        "MODULATE_HORIZON",
        "PERTURB_TIMING",
    }


def test_challenge_reports_fragility_without_becoming_market_evidence():
    receipt=MystiqueCounterfactualVariations().challenge(parent())
    assert receipt.worlds_tested == 8
    assert receipt.worlds_survived + receipt.worlds_failed == 8
    assert 0.0 <= receipt.fragility_score <= 1.0
    assert receipt.contamination_guard_passed is True
    assert receipt.observed_namespace_untouched is True
    assert receipt.prospective_evidence_eligible is False
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_remove_depth_recovery_can_expose_dependency():
    p=parent(metrics={
        "motif_strength": .72,
        "relationship_stability": .72,
        "flow_support": .72,
        "depth_recovery": .90,
        "timing_coherence": .72,
        "lineage_diversity": .72,
        "horizon_compatibility": .72,
        "cost_clearance": .72,
    })
    engine=MystiqueCounterfactualVariations()
    receipt=engine.challenge(
        p,
        variations=(
            CounterfactualVariation(
                "remove-depth","REMOVE_DEPTH_RECOVERY","depth_recovery",1.0,
                "remove recovery",
            ),
        ),
    )
    assert receipt.worlds_tested == 1
    assert receipt.worlds_failed == 1
    assert "REMOVE_DEPTH_RECOVERY" in receipt.critical_dependencies


def test_synthetic_survival_does_not_promote_parent():
    p=parent(metrics={
        "motif_strength": .95,
        "relationship_stability": .95,
        "flow_support": .95,
        "depth_recovery": .95,
        "timing_coherence": .95,
        "lineage_diversity": .95,
        "horizon_compatibility": .95,
        "cost_clearance": .95,
    })
    receipt=MystiqueCounterfactualVariations().challenge(
        p,
        variations=(
            CounterfactualVariation(
                "small-timing","PERTURB_TIMING","timing_coherence",.1,
                "small synthetic timing perturbation",
            ),
        ),
    )
    assert receipt.worlds_survived == 1
    assert receipt.fragility_score == 0.0
    assert receipt.prospective_evidence_eligible is False
    assert receipt.authority == "research_evidence_only_no_execution_or_promotion_authority"


def test_parent_observed_metrics_are_not_mutated_by_variations():
    p=parent()
    before=dict(p.metrics)
    MystiqueCounterfactualVariations().challenge(p)
    assert dict(p.metrics) == before
    assert p.namespace == OBSERVED_NAMESPACE
