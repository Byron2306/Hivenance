from __future__ import annotations

from strategies.relative_value_lab.causal_cascade import CascadeEvent, CascadeLink, CausalCascade
from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.hive_pulse import HivePulseEngine
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS="ws-cascade"
WH="sha256:"+"a"*64
STRUCT="sha256:"+"1"*64
STAT="sha256:"+"2"*64
MICRO="sha256:"+"3"*64


def _music():
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
        ("s2","structural",STRUCT,16000),
        ("t2","statistical",STAT,21000),
        ("m2","microstructure",MICRO,26000),
    ]
    for bee,fam,lin,ts in rows:
        msg=bus.build_message(
            bee_id=bee,family=fam,lineage_digest=lin,
            message_type="WAGGLE" if bee=="s" else "FOLLOW",
            scope="A/USD__B/USD",hypothesis_id="motif-c",
            world_state_id=WS,world_state_hash=WH,observed_at_ms=ts,
            evidence_root="sha256:"+bee[0]*64,horizon_seconds=10,
            direction="LONG_A_SHORT_B",expected_move_bps=2.0,
            uncertainty=.25,independent_claimed=True,
        )
        rec=bus.publish(msg,current_world_state_id=WS,current_world_state_hash=WH,now_ms=ts)
        acc.ingest(message=msg,receipt=rec)
    return acc


def _epoch():
    return ResearchGovernanceEpochService.start_epoch(
        world_state_id=WS,world_state_hash=WH,started_at_ms=0,ttl_ms=120000,
        genre_mode="watchful",strictness_level="standard",scope="relative_value_lab",
    )


def _cascade():
    events=[
        CascadeEvent("e1",1000,"sell_burst","pair:A/B",WS,WH,"sha256:"+"4"*64,"microstructure","l1","A/B",("A","B")),
        CascadeEvent("e2",3000,"book_depletion","pair:A/B",WS,WH,"sha256:"+"5"*64,"book","l2","A/B",("A","B")),
        CascadeEvent("e3",6000,"relative_excursion","connected_pairs:A",WS,WH,"sha256:"+"6"*64,"structural","l3",None,("A","B","C")),
        CascadeEvent("e4",9000,"depth_recovery","asset:A",WS,WH,"sha256:"+"7"*64,"microstructure","l4",None,("A",)),
    ]
    links=[
        CascadeLink("e1","e2","flow_to_depletion","sha256:"+"8"*64,.85),
        CascadeLink("e2","e3","depletion_to_excursion","sha256:"+"9"*64,.80),
        CascadeLink("e3","e4","excursion_to_recovery","sha256:"+"b"*64,.80),
    ]
    return CausalCascade().build(events=events,links=links)


def test_queen_hears_cascade_and_hive_pulse_as_crescendo():
    acc=_music()
    motif=acc.score("motif-c")
    ent=PolyphonicEntrainment().score(hypothesis_id="motif-c",notes=acc.notes("motif-c"))
    cascade=_cascade()
    pulse=HivePulseEngine.from_cascade(
        cascade,pulse_class="DISCOVERY_PULSE",scope="asset:A",
        issued_at_ms=10000,ttl_ms=30000,lineage_root="hive",
        evidence_root="sha256:"+"c"*64,
    )
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-c",notes=acc.notes("motif-c"),
        motif=motif,entrainment=ent,epoch=_epoch(),
        cascade=cascade,hive_pulses=(pulse,),
        now_ms=15000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.cascade_strength == cascade.propagation_strength
    assert receipt.cascade_crescendo == cascade.crescendo
    assert receipt.hive_pulse_energy > 0.0
    assert "FOLLOW_CASCADE" in receipt.conducting_gestures
    assert "EXPAND_LISTENING_SCOPE" in receipt.conducting_gestures
    assert any(t.notation=="TRACE_PROPAGATION" for t in receipt.notation_tokens)
    loki=next(s for s in receipt.triune_scores if s.mind=="LOKI")
    assert "challenge_propagation_mechanism" in loki.invitations
    assert receipt.execution_eligible is False


def test_negative_pulse_becomes_safety_accent_not_positive_authority():
    acc=_music()
    motif=acc.score("motif-c")
    ent=PolyphonicEntrainment().score(hypothesis_id="motif-c",notes=acc.notes("motif-c"))
    pulse=HivePulseEngine.emit(
        pulse_class="FREEZE_PULSE",scope="pair:A/B",issued_at_ms=10000,ttl_ms=30000,
        severity=.9,confidence=.9,amplitude=.9,world_state_id=WS,
        lineage_root="hive",evidence_root="sha256:"+"d"*64,
    )
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-c",notes=acc.notes("motif-c"),
        motif=motif,entrainment=ent,epoch=_epoch(),
        hive_pulses=(pulse,),
        now_ms=12000,world_state_id=WS,world_state_hash=WH,
    )
    assert "HOLD_FREEZE_ACCENT" in receipt.conducting_gestures
    assert any(t.notation=="HOLD_FREEZE_ACCENT" for t in receipt.notation_tokens)
    assert all(t.execution_eligible is False for t in receipt.notation_tokens)
    michael=next(s for s in receipt.triune_scores if s.mind=="MICHAEL")
    assert "honour_negative_pulse" in michael.invitations
