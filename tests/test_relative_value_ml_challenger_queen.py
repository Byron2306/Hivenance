from __future__ import annotations

from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.ml_challenger import (
    LearnedCalibration,
    LearnedChallenger,
    LearnedChallengerForecast,
    LearnedModelProvenance,
)
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS="ws-ml-q"
WH="sha256:"+"a"*64
STRUCT="sha256:"+"1"*64
STAT="sha256:"+"2"*64
MICRO="sha256:"+"3"*64


def build_music():
    reg=LineageRegistry([
        BeeLineage(STRUCT,"structural",STRUCT),
        BeeLineage(STAT,"statistical",STAT),
        BeeLineage(MICRO,"microstructure",MICRO),
    ])
    bus=WaggleProtocol(registry=reg)
    acc=MusicalMotifAccumulator(registry=reg)
    rows=[
        ("s","structural",STRUCT,1000),
        ("t","statistical",STAT,6000),
        ("m","microstructure",MICRO,11000),
    ]
    for bee,fam,lin,ts in rows:
        msg=bus.build_message(
            bee_id=bee,family=fam,lineage_digest=lin,
            message_type="WAGGLE" if ts==1000 else "FOLLOW",
            scope="A/USD__B/USD",hypothesis_id="motif-ml-q",
            world_state_id=WS,world_state_hash=WH,observed_at_ms=ts,
            evidence_root="sha256:"+bee[0]*64,
            horizon_seconds=10,direction="LONG_A_SHORT_B",
            expected_move_bps=2.0,uncertainty=.2,independent_claimed=True,
        )
        rec=bus.publish(
            msg,current_world_state_id=WS,current_world_state_hash=WH,now_ms=ts
        )
        acc.ingest(message=msg,receipt=rec)

    motif=acc.score("motif-ml-q")
    ent=PolyphonicEntrainment().score(
        hypothesis_id="motif-ml-q",notes=acc.notes("motif-ml-q")
    )
    epoch=ResearchGovernanceEpochService.start_epoch(
        world_state_id=WS,world_state_hash=WH,started_at_ms=0,ttl_ms=1_000_000,
        genre_mode="watchful",strictness_level="standard",scope="relative_value_lab",
    )
    return acc,motif,ent,epoch


def learned(
    *,
    predicted=-2.5,
    drift=.05,
    now_ms=31_000,
    synthetic=False,
    shared=False,
    uncertainty=1.0,
):
    prov=LearnedModelProvenance(
        model_id="learned-alpha",
        model_version="1.0",
        model_artifact_digest="sha256:"+"4"*64,
        training_lineage_digest="sha256:"+"5"*64,
        feature_lineage_digest="sha256:"+"6"*64,
        training_cutoff_ms=10_000,
        validation_start_ms=10_001,
        validation_end_ms=20_000,
        dependence_group="ridge-lineage" if shared else "learned-independent",
        synthetic_training_used=synthetic,
    )
    cal=LearnedCalibration(
        samples=200,
        mae_bps=1.0,
        rmse_bps=1.4,
        sign_accuracy=.60,
        calibration_error=.08,
        baseline_delta_bps=.2,
        leave_one_pair_score=.70,
        leave_one_asset_score=.68,
    )
    fc=LearnedChallengerForecast(
        hypothesis_id="motif-ml-q",
        pair_id="A/USD__B/USD",
        horizon_seconds=10,
        observed_at_ms=30_000,
        predicted_signed_bps=predicted,
        uncertainty_bps=uncertainty,
        world_state_id=WS,
        world_state_hash=WH,
        evidence_root="sha256:"+"7"*64,
    )
    return LearnedChallenger().score(
        forecast=fc,
        provenance=prov,
        calibration=cal,
        now_ms=now_ms,
        drift_score=drift,
        known_dependence_groups=("ridge-lineage",) if shared else (),
    )


def test_queen_hears_healthy_learned_counterpoint_without_granting_authority():
    acc,motif,ent,epoch=build_music()
    challenger=learned(predicted=-2.5)
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-ml-q",notes=acc.notes("motif-ml-q"),
        motif=motif,entrainment=ent,epoch=epoch,
        learned_challengers=(challenger,),
        now_ms=40_000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.learned_voice_count==1
    assert receipt.learned_independent_count==1
    assert receipt.learned_dissent==1.0
    assert "HEAR_LEARNED_COUNTERPOINT" in receipt.conducting_gestures
    assert any(t.notation=="CHALLENGE_LEARNED_VOICE" for t in receipt.notation_tokens)
    loki=next(s for s in receipt.triune_scores if s.mind=="LOKI")
    assert "preserve_ml_counterpoint" in loki.invitations
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_drifting_learned_voice_is_retuned_not_promoted():
    acc,motif,ent,epoch=build_music()
    challenger=learned(predicted=2.5,drift=.30)
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-ml-q",notes=acc.notes("motif-ml-q"),
        motif=motif,entrainment=ent,epoch=epoch,
        learned_challengers=(challenger,),
        now_ms=40_000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.learned_drift_pressure>.55
    assert "RETUNE_LEARNED_VOICE" in receipt.conducting_gestures
    assert any(t.notation=="RETUNE_LEARNED_VOICE" for t in receipt.notation_tokens)
    michael=next(s for s in receipt.triune_scores if s.mind=="MICHAEL")
    assert "retune_learned_voice" in michael.invitations


def test_dependent_learned_voice_remains_audible_but_nonindependent():
    acc,motif,ent,epoch=build_music()
    challenger=learned(predicted=-2.5,shared=True)
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-ml-q",notes=acc.notes("motif-ml-q"),
        motif=motif,entrainment=ent,epoch=epoch,
        learned_challengers=(challenger,),
        now_ms=40_000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.learned_voice_count==1
    assert receipt.learned_independent_count==0
    michael=next(s for s in receipt.triune_scores if s.mind=="MICHAEL")
    assert "preserve_ml_dependence_labels" in michael.invitations


def test_synthetic_trained_learned_voice_never_becomes_edge_truth():
    acc,motif,ent,epoch=build_music()
    challenger=learned(predicted=-2.5,synthetic=True)
    assert challenger.prospective_edge_evidence is False
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-ml-q",notes=acc.notes("motif-ml-q"),
        motif=motif,entrainment=ent,epoch=epoch,
        learned_challengers=(challenger,),
        now_ms=40_000,world_state_id=WS,world_state_hash=WH,
    )
    loki=next(s for s in receipt.triune_scores if s.mind=="LOKI")
    assert "keep_synthetic_ml_out_of_edge_truth" in loki.invitations
    assert receipt.execution_eligible is False


def test_high_uncertainty_softens_learned_dynamic():
    acc,motif,ent,epoch=build_music()
    challenger=learned(predicted=2.5,uncertainty=5.0)
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-ml-q",notes=acc.notes("motif-ml-q"),
        motif=motif,entrainment=ent,epoch=epoch,
        learned_challengers=(challenger,),
        now_ms=40_000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.learned_uncertainty_pressure>.70
    assert "SOFTEN_LEARNED_DYNAMIC" in receipt.conducting_gestures
