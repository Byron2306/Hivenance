from __future__ import annotations

from strategies.relative_value_lab.cognitive_metabolism import (
    CognitiveMetabolism,
    MetabolicObservation,
)
from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS="ws-metab"
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
            scope="A/USD__B/USD",hypothesis_id="motif-metab",
            world_state_id=WS,world_state_hash=WH,observed_at_ms=ts,
            evidence_root="sha256:"+bee[0]*64,horizon_seconds=10,
            direction="LONG_A_SHORT_B",expected_move_bps=2.0,
            uncertainty=.25,independent_claimed=True,
        )
        rec=bus.publish(msg,current_world_state_id=WS,current_world_state_hash=WH,now_ms=ts)
        acc.ingest(message=msg,receipt=rec)
    motif=acc.score("motif-metab")
    ent=PolyphonicEntrainment().score(
        hypothesis_id="motif-metab",notes=acc.notes("motif-metab")
    )
    epoch=ResearchGovernanceEpochService.start_epoch(
        world_state_id=WS,world_state_hash=WH,started_at_ms=0,ttl_ms=120000,
        genre_mode="watchful",strictness_level="standard",scope="relative_value_lab",
    )
    return acc,motif,ent,epoch


def metabolic(**kwargs):
    base=dict(
        observation_id="metab-1",
        timestamp_ms=12000,
        context_units_consumed=400.0,
        model_evaluations=4,
        tool_evaluations=3,
        independent_evidence_units=4.0,
        duplicate_evidence_units=1.0,
        useful_settled_information_units=2.0,
        information_gain_units=1.5,
        baseline_confidence=.8,
        current_confidence=.75,
        world_state_id=WS,
        world_state_hash=WH,
    )
    base.update(kwargs)
    return CognitiveMetabolism().score(MetabolicObservation(**base))


def test_queen_thins_orchestration_under_high_metabolic_strain():
    acc,motif,ent,epoch=build_music()
    metabolism=metabolic(
        context_units_consumed=3000.0,
        model_evaluations=40,
        tool_evaluations=40,
        independent_evidence_units=1.0,
        duplicate_evidence_units=8.0,
        useful_settled_information_units=0.0,
        information_gain_units=.05,
        baseline_confidence=.9,
        current_confidence=.45,
    )
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-metab",notes=acc.notes("motif-metab"),
        motif=motif,entrainment=ent,epoch=epoch,metabolism=metabolism,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.metabolic_strain == metabolism.metabolic_strain
    assert receipt.cognitive_breath == metabolism.breath
    assert "THIN_ORCHESTRATION" in receipt.conducting_gestures
    assert any(t.notation=="THIN_ORCHESTRATION" for t in receipt.notation_tokens)
    assert any(t.notation=="LET_MOTIF_REST" for t in receipt.notation_tokens)
    assert receipt.execution_eligible is False


def test_duplicate_burn_invites_fresh_evidence_and_loki_counterpoint():
    acc,motif,ent,epoch=build_music()
    metabolism=metabolic(
        independent_evidence_units=1.0,
        duplicate_evidence_units=9.0,
        information_gain_units=.2,
    )
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-metab",notes=acc.notes("motif-metab"),
        motif=motif,entrainment=ent,epoch=epoch,metabolism=metabolism,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert "INVITE_FRESH_TIMBRE" in receipt.conducting_gestures
    assert any(t.notation=="SEEK_FRESH_EVIDENCE" for t in receipt.notation_tokens)
    loki=next(s for s in receipt.triune_scores if s.mind=="LOKI")
    assert "seek_non_echo_evidence" in loki.invitations


def test_unresolved_denominator_remains_unresolved_in_queen_score():
    acc,motif,ent,epoch=build_music()
    metabolism=metabolic(
        useful_settled_information_units=0.0,
        context_units_consumed=1600.0,
        model_evaluations=20,
        tool_evaluations=15,
        information_gain_units=.1,
    )
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-metab",notes=acc.notes("motif-metab"),
        motif=motif,entrainment=ent,epoch=epoch,metabolism=metabolism,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.metabolic_cbr is None
    assert receipt.metabolic_tbcr is None
    michael=next(s for s in receipt.triune_scores if s.mind=="MICHAEL")
    assert "keep_burn_denominator_unresolved" in michael.invitations


def test_fresh_independent_evidence_sustains_cognitive_breath():
    acc,motif,ent,epoch=build_music()
    metabolism=metabolic(
        context_units_consumed=120.0,
        model_evaluations=2,
        tool_evaluations=1,
        independent_evidence_units=8.0,
        duplicate_evidence_units=0.0,
        information_gain_units=2.0,
        useful_settled_information_units=2.0,
        baseline_confidence=.8,
        current_confidence=.8,
    )
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-metab",notes=acc.notes("motif-metab"),
        motif=motif,entrainment=ent,epoch=epoch,metabolism=metabolism,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.cognitive_breath > .7
    assert "SUSTAIN_COGNITIVE_BREATH" in receipt.conducting_gestures
    assert receipt.promotion_eligible is False
