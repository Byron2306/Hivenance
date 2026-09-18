from __future__ import annotations

from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.mystique_variations import (
    CounterfactualVariation,
    MystiqueCounterfactualVariations,
    MystiqueObservedScore,
)
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS="ws-mystique"
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
            scope="A/USD__B/USD",hypothesis_id="motif-m",
            world_state_id=WS,world_state_hash=WH,
            observed_at_ms=ts,evidence_root="sha256:"+bee[0]*64,
            horizon_seconds=10,direction="LONG_A_SHORT_B",
            expected_move_bps=2.0,uncertainty=.2,independent_claimed=True,
        )
        rec=bus.publish(msg,current_world_state_id=WS,current_world_state_hash=WH,now_ms=ts)
        acc.ingest(message=msg,receipt=rec)
    motif=acc.score("motif-m")
    ent=PolyphonicEntrainment().score(hypothesis_id="motif-m",notes=acc.notes("motif-m"))
    epoch=ResearchGovernanceEpochService.start_epoch(
        world_state_id=WS,world_state_hash=WH,started_at_ms=0,ttl_ms=120000,
        genre_mode="watchful",strictness_level="standard",scope="relative_value_lab",
    )
    return acc,motif,ent,epoch


def parent(metrics):
    return MystiqueObservedScore(
        score_id="observed-score-1",
        hypothesis_id="motif-m",
        world_state_id=WS,
        world_state_hash=WH,
        observed_at_ms=11000,
        metrics=metrics,
        evidence_roots=("sha256:"+"4"*64,"sha256:"+"5"*64),
        lineage_roots=("l1","l2","l3"),
    )


def test_strong_cadence_invites_mystique_before_resolution():
    acc,motif,ent,epoch=build_music()
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-m",notes=acc.notes("motif-m"),
        motif=motif,entrainment=ent,epoch=epoch,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert motif.cadence_strength > .55
    assert any(t.notation=="RUN_MYSTIQUE_VARIATIONS" for t in receipt.notation_tokens)
    assert receipt.execution_eligible is False


def test_fragile_mystique_result_holds_cadence_and_arms_loki():
    acc,motif,ent,epoch=build_music()
    mystique=MystiqueCounterfactualVariations().challenge(
        parent({
            "motif_strength":.72,
            "relationship_stability":.72,
            "flow_support":.72,
            "depth_recovery":.92,
            "timing_coherence":.72,
            "lineage_diversity":.72,
            "horizon_compatibility":.72,
            "cost_clearance":.72,
        }),
        variations=(
            CounterfactualVariation(
                "remove-depth","REMOVE_DEPTH_RECOVERY","depth_recovery",1.0,
                "remove depth recovery",
            ),
        ),
    )
    assert mystique.fragility_score == 1.0

    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-m",notes=acc.notes("motif-m"),
        motif=motif,entrainment=ent,epoch=epoch,mystique=mystique,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.mystique_fragility == 1.0
    assert "HOLD_FRAGILE_CADENCE" in receipt.conducting_gestures
    assert any(t.notation=="CHALLENGE_FRAGILE_CADENCE" for t in receipt.notation_tokens)

    loki=next(s for s in receipt.triune_scores if s.mind=="LOKI")
    michael=next(s for s in receipt.triune_scores if s.mind=="MICHAEL")
    assert "challenge_fragile_cadence" in loki.invitations
    assert "attack_critical_dependencies" in loki.invitations
    assert "keep_synthetic_out_of_prospective_truth" in michael.invitations


def test_synthetic_robustness_is_not_prospective_truth():
    acc,motif,ent,epoch=build_music()
    mystique=MystiqueCounterfactualVariations().challenge(
        parent({
            "motif_strength":.98,
            "relationship_stability":.98,
            "flow_support":.98,
            "depth_recovery":.98,
            "timing_coherence":.98,
            "lineage_diversity":.98,
            "horizon_compatibility":.98,
            "cost_clearance":.98,
        }),
        variations=(
            CounterfactualVariation(
                "small-timing","PERTURB_TIMING","timing_coherence",.05,
                "small synthetic perturbation",
            ),
        ),
    )
    assert mystique.survival_rate == 1.0
    assert mystique.prospective_evidence_eligible is False

    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-m",notes=acc.notes("motif-m"),
        motif=motif,entrainment=ent,epoch=epoch,mystique=mystique,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert "NOTE_SYNTHETIC_ROBUSTNESS" in receipt.conducting_gestures
    assert receipt.mystique_contamination_guard is True
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
