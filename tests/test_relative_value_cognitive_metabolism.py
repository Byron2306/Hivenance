from __future__ import annotations

from strategies.relative_value_lab.cognitive_metabolism import (
    CognitiveMetabolism,
    MetabolicObservation,
)


def obs(**overrides):
    base=dict(
        observation_id="m1",
        timestamp_ms=1000,
        context_units_consumed=400.0,
        model_evaluations=4,
        tool_evaluations=3,
        independent_evidence_units=4.0,
        duplicate_evidence_units=1.0,
        useful_settled_information_units=2.0,
        information_gain_units=1.5,
        baseline_confidence=.8,
        current_confidence=.75,
        world_state_id="ws-1",
        world_state_hash="sha256:"+"a"*64,
    )
    base.update(overrides)
    return MetabolicObservation(**base)


def test_cbr_tbcr_use_useful_settled_information_denominator():
    receipt=CognitiveMetabolism().score(obs())
    assert receipt.cbr == 200.0
    assert receipt.tbcr == 3.5
    assert receipt.denominator_resolved is True
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_unsettled_metabolism_does_not_fake_denominator():
    receipt=CognitiveMetabolism().score(obs(
        useful_settled_information_units=0.0,
        context_units_consumed=1200.0,
        model_evaluations=20,
        tool_evaluations=20,
        information_gain_units=.1,
    ))
    assert receipt.cbr is None
    assert receipt.tbcr is None
    assert receipt.denominator_resolved is False
    assert receipt.unresolved_burn > 0.0
    assert "settlement_denominator_unresolved" in receipt.reasons


def test_duplicate_evidence_increases_burn_and_reduces_breath():
    engine=CognitiveMetabolism()
    fresh=engine.score(obs(
        independent_evidence_units=9.0,
        duplicate_evidence_units=1.0,
    ))
    echo=engine.score(obs(
        independent_evidence_units=1.0,
        duplicate_evidence_units=9.0,
    ))
    assert echo.duplicate_pressure > fresh.duplicate_pressure
    assert echo.metabolic_strain > fresh.metabolic_strain
    assert echo.breath < fresh.breath


def test_confidence_degradation_index_retains_metatron_semantics():
    receipt=CognitiveMetabolism().score(obs(
        baseline_confidence=.8,
        current_confidence=.4,
    ))
    assert receipt.cdi == .5
    assert "confidence_degrading" in receipt.reasons


def test_high_burn_low_information_becomes_fatigue_not_authority():
    receipt=CognitiveMetabolism().score(obs(
        context_units_consumed=3000.0,
        model_evaluations=40,
        tool_evaluations=40,
        information_gain_units=.05,
        independent_evidence_units=1,
        duplicate_evidence_units=8,
        useful_settled_information_units=0.0,
        baseline_confidence=.9,
        current_confidence=.5,
    ))
    assert receipt.texture in {"UNSETTLED_FATIGUE","OVERREHEARSING","FATIGUED","ECHO_BURN"}
    assert receipt.metabolic_strain > .5
    assert receipt.execution_eligible is False


def test_fresh_evidence_can_restore_breath():
    receipt=CognitiveMetabolism().score(obs(
        context_units_consumed=150.0,
        model_evaluations=2,
        tool_evaluations=1,
        independent_evidence_units=8,
        duplicate_evidence_units=0,
        information_gain_units=2.0,
        useful_settled_information_units=2.0,
        baseline_confidence=.8,
        current_confidence=.8,
    ))
    assert receipt.evidence_novelty == 1.0
    assert receipt.breath > .7
    assert "fresh_independent_evidence" in receipt.reasons
