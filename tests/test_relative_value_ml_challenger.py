from __future__ import annotations

from strategies.relative_value_lab.ml_challenger import (
    LearnedCalibration,
    LearnedChallenger,
    LearnedChallengerForecast,
    LearnedModelProvenance,
)


def provenance(**overrides):
    base=dict(
        model_id="learned-alpha",
        model_version="1.0.0",
        model_artifact_digest="sha256:"+"1"*64,
        training_lineage_digest="sha256:"+"2"*64,
        feature_lineage_digest="sha256:"+"3"*64,
        training_cutoff_ms=10_000,
        validation_start_ms=10_001,
        validation_end_ms=20_000,
        dependence_group="learned-family-a",
        synthetic_training_used=False,
    )
    base.update(overrides)
    return LearnedModelProvenance(**base)


def calibration(**overrides):
    base=dict(
        samples=200,
        mae_bps=1.0,
        rmse_bps=1.4,
        sign_accuracy=.60,
        calibration_error=.08,
        baseline_delta_bps=.2,
        leave_one_pair_score=.70,
        leave_one_asset_score=.68,
    )
    base.update(overrides)
    return LearnedCalibration(**base)


def forecast(**overrides):
    base=dict(
        hypothesis_id="motif-ml",
        pair_id="A/USD__B/USD",
        horizon_seconds=10,
        observed_at_ms=30_000,
        predicted_signed_bps=2.5,
        uncertainty_bps=1.0,
        world_state_id="ws-ml",
        world_state_hash="sha256:"+"a"*64,
        evidence_root="sha256:"+"4"*64,
    )
    base.update(overrides)
    return LearnedChallengerForecast(**base)


def test_healthy_provenance_bound_challenger_can_be_independent_research_voice():
    receipt=LearnedChallenger().score(
        forecast=forecast(),
        provenance=provenance(),
        calibration=calibration(),
        now_ms=31_000,
        drift_score=.05,
    )
    assert receipt.direction=="LONG_A_SHORT_B"
    assert receipt.voice_health>.55
    assert receipt.independent_vote_eligible is True
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_shared_dependence_group_remains_audible_but_not_independent():
    receipt=LearnedChallenger().score(
        forecast=forecast(),
        provenance=provenance(dependence_group="ridge-lineage"),
        calibration=calibration(),
        now_ms=31_000,
        drift_score=.05,
        known_dependence_groups=("ridge-lineage",),
    )
    assert receipt.independent_vote_eligible is False
    assert "shared_dependence_group" in receipt.reasons
    assert receipt.voice_health>0.0


def test_stale_or_drifting_challenger_loses_health():
    engine=LearnedChallenger()
    healthy=engine.score(
        forecast=forecast(),
        provenance=provenance(),
        calibration=calibration(),
        now_ms=31_000,
        drift_score=.05,
    )
    sick=engine.score(
        forecast=forecast(),
        provenance=provenance(),
        calibration=calibration(),
        now_ms=700_000,
        drift_score=.6,
    )
    assert sick.voice_health < healthy.voice_health
    assert "challenger_stale" in sick.reasons
    assert "model_drift_audible" in sick.reasons


def test_validation_overlap_prevents_independent_vote():
    receipt=LearnedChallenger().score(
        forecast=forecast(observed_at_ms=18_000),
        provenance=provenance(validation_end_ms=20_000),
        calibration=calibration(),
        now_ms=18_500,
        drift_score=.05,
    )
    assert receipt.independent_vote_eligible is False
    assert "validation_window_overlaps_forecast" in receipt.reasons


def test_synthetic_training_never_becomes_prospective_edge_evidence():
    receipt=LearnedChallenger().score(
        forecast=forecast(),
        provenance=provenance(synthetic_training_used=True),
        calibration=calibration(),
        now_ms=31_000,
        drift_score=.05,
    )
    assert receipt.synthetic_training_used is True
    assert receipt.prospective_edge_evidence is False
    assert receipt.independent_vote_eligible is False
    assert "synthetic_training_not_edge_evidence" in receipt.reasons


def test_missing_calibration_and_generalization_are_explicit():
    receipt=LearnedChallenger().score(
        forecast=forecast(),
        provenance=provenance(),
        calibration=calibration(
            samples=5,
            calibration_error=None,
            baseline_delta_bps=None,
            leave_one_pair_score=None,
            leave_one_asset_score=None,
        ),
        now_ms=31_000,
        drift_score=.05,
    )
    assert "calibration_missing" in receipt.reasons
    assert "baseline_comparison_missing" in receipt.reasons
    assert "generalization_diagnostics_missing" in receipt.reasons
    assert receipt.independent_vote_eligible is False


def test_challenger_can_abstain_without_disappearing():
    receipt=LearnedChallenger().score(
        forecast=forecast(predicted_signed_bps=.01),
        provenance=provenance(),
        calibration=calibration(),
        now_ms=31_000,
        drift_score=.05,
    )
    assert receipt.direction=="ABSTAIN"
    assert "challenger_abstains" in receipt.reasons
    assert receipt.execution_eligible is False


def test_synthesis_state_can_only_make_challenger_more_cautious():
    engine=LearnedChallenger()
    healthy=engine.score(
        forecast=forecast(),
        provenance=provenance(),
        calibration=calibration(),
        now_ms=31_000,
        drift_score=.05,
    )
    cautious=engine.score(
        forecast=forecast(),
        provenance=provenance(),
        calibration=calibration(),
        now_ms=31_000,
        drift_score=.05,
        synthesis_state={
            "hierarchical_win_probability": .78,
            "hierarchical_edge_positive_probability": .81,
            "uncertainty": .92,
            "change_point_probability": .88,
        },
    )
    assert cautious.voice_health < healthy.voice_health
    assert cautious.synthesis_win_probability == .78
    assert cautious.synthesis_edge_positive_probability == .81
    assert cautious.synthesis_uncertainty == .92
    assert cautious.synthesis_change_point_probability == .88
    assert "synthesis_change_point_pressure_high" in cautious.reasons
    assert cautious.execution_eligible is False
    assert cautious.promotion_eligible is False
