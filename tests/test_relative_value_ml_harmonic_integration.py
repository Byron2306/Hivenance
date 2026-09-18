from __future__ import annotations

from strategies.relative_value_lab.evaluation import WalkForwardPrediction
from strategies.relative_value_lab.harmonic_governance import HarmonicForecastGovernance
from strategies.relative_value_lab.ml_challenger import (
    LearnedCalibration,
    LearnedChallenger,
    LearnedChallengerForecast,
    LearnedModelProvenance,
)


PAIR="A/USD__B/USD"
WS="ws-ml-h"
WH="sha256:"+"a"*64


def pred(model_id,value,ts=30000,horizon=10):
    return WalkForwardPrediction(
        schema="hivenance_relative_value_walk_forward_prediction_v1",
        example_id=f"{model_id}-{horizon}-{ts}",
        pair_id=PAIR,
        timestamp_ms=ts,
        horizon_seconds=horizon,
        model_id=model_id,
        predicted_signed_bps=value,
        realized_signed_bps=1.0,
        directional_gross_bps=1.0,
        spread_cost_proxy_bps=1.0,
        directional_after_spread_proxy_bps=0.0,
        train_samples=100,
    )


def challenger(model_id,dep,predicted,*,healthy=True,shared=False):
    prov=LearnedModelProvenance(
        model_id=model_id,
        model_version="1.0",
        model_artifact_digest="sha256:"+model_id[0]*64,
        training_lineage_digest="sha256:"+"2"*64,
        feature_lineage_digest="sha256:"+"3"*64,
        training_cutoff_ms=10000,
        validation_start_ms=10001,
        validation_end_ms=20000,
        dependence_group=dep,
        synthetic_training_used=False,
    )
    cal=LearnedCalibration(
        samples=200 if healthy else 5,
        mae_bps=1.0,
        rmse_bps=1.4,
        sign_accuracy=.6,
        calibration_error=.08 if healthy else None,
        baseline_delta_bps=.2 if healthy else None,
        leave_one_pair_score=.7 if healthy else None,
        leave_one_asset_score=.68 if healthy else None,
    )
    fc=LearnedChallengerForecast(
        hypothesis_id="motif",
        pair_id=PAIR,
        horizon_seconds=10,
        observed_at_ms=30000,
        predicted_signed_bps=predicted,
        uncertainty_bps=1.0,
        world_state_id=WS,
        world_state_hash=WH,
        evidence_root="sha256:"+"4"*64,
    )
    return LearnedChallenger().score(
        forecast=fc,
        provenance=prov,
        calibration=cal,
        now_ms=31000,
        drift_score=.05,
        known_dependence_groups=(dep,) if shared else (),
    )


def test_multiple_learned_models_collapse_to_one_family_voice():
    engine=HarmonicForecastGovernance()
    rows=[
        pred("relative_value_ou_mean_reversion_v1",2.0),
        pred("relative_value_expanding_ridge_v1",2.0),
    ]
    receipt=engine.score(
        pair_id=PAIR,timestamp_ms=30000,predictions=rows,
        challengers=(
            challenger("learned-a","ml-a",2.5),
            challenger("learned-b","ml-b",2.0),
        ),
    )
    learned=[v for v in receipt.voices if v.family=="learned"]
    assert len(learned)==1
    assert learned[0].independent is True
    assert "learned" in receipt.independent_families


def test_dependent_learned_voice_does_not_increase_independent_family_count():
    engine=HarmonicForecastGovernance()
    rows=[
        pred("relative_value_ou_mean_reversion_v1",2.0),
        pred("relative_value_expanding_ridge_v1",2.0),
    ]
    receipt=engine.score(
        pair_id=PAIR,timestamp_ms=30000,predictions=rows,
        challengers=(challenger("learned-a","ridge-lineage",-2.0,shared=True),),
    )
    learned=next(v for v in receipt.voices if v.family=="learned")
    assert learned.independent is False
    assert "learned" not in receipt.independent_families
    assert "learned_challenger_audible_but_nonindependent" in receipt.reasons


def test_unhealthy_learned_voice_remains_audible_but_nonindependent():
    engine=HarmonicForecastGovernance()
    receipt=engine.score(
        pair_id=PAIR,timestamp_ms=30000,
        predictions=[pred("relative_value_ou_mean_reversion_v1",2.0)],
        challengers=(challenger("learned-a","ml-a",-2.0,healthy=False),),
    )
    learned=next(v for v in receipt.voices if v.family=="learned")
    assert learned.independent is False


def test_learned_disagreement_remains_same_horizon_dissonance():
    engine=HarmonicForecastGovernance()
    receipt=engine.score(
        pair_id=PAIR,timestamp_ms=30000,
        predictions=[
            pred("relative_value_ou_mean_reversion_v1",2.0),
            pred("relative_value_expanding_ridge_v1",2.0),
        ],
        challengers=(challenger("learned-a","ml-a",-2.5),),
    )
    state=next(s for s in receipt.horizon_states if s.horizon_seconds==10)
    assert "learned" in state.independent_families
    assert state.discord_score > 0.0
    assert "direction" not in receipt.to_dict()
