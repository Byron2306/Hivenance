from __future__ import annotations

from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.edge_chorus_harmony import (
    EdgeChorus,
    EdgeChorusObservation,
    EdgeChorusSpec,
)
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.temporal_texture import TemporalTexture
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS_ID = "ws-polyphia"
WS_HASH = "sha256:" + "a" * 64
STRUCT = "sha256:" + "1" * 64
STAT = "sha256:" + "2" * 64
MICRO = "sha256:" + "3" * 64


def _music(times=(1000, 6000, 11000, 16000, 21000, 26000)):
    reg = LineageRegistry([
        BeeLineage(STRUCT, "structural", STRUCT),
        BeeLineage(STAT, "statistical", STAT),
        BeeLineage(MICRO, "microstructure", MICRO),
    ])
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)
    rows = [
        ("s","structural",STRUCT),
        ("t","statistical",STAT),
        ("m","microstructure",MICRO),
        ("s2","structural",STRUCT),
        ("t2","statistical",STAT),
        ("m2","microstructure",MICRO),
    ]
    for ts,(bee,fam,lin) in zip(times,rows):
        msg=bus.build_message(
            bee_id=bee,family=fam,lineage_digest=lin,
            message_type="WAGGLE" if bee=="s" else "FOLLOW",
            scope="A/USD__B/USD",hypothesis_id="motif-p",
            world_state_id=WS_ID,world_state_hash=WS_HASH,
            observed_at_ms=ts,evidence_root="sha256:"+bee[0]*64,
            horizon_seconds=10,direction="LONG_A_SHORT_B",
            expected_move_bps=2.0,uncertainty=.25,independent_claimed=True,
        )
        rec=bus.publish(msg,current_world_state_id=WS_ID,current_world_state_hash=WS_HASH,now_ms=ts)
        acc.ingest(message=msg,receipt=rec)
    return acc


def _epoch():
    return ResearchGovernanceEpochService.start_epoch(
        world_state_id=WS_ID,world_state_hash=WS_HASH,
        started_at_ms=0,ttl_ms=120000,
        genre_mode="watchful",strictness_level="standard",
        scope="relative_value_lab",
    )


def _edge(consonant=True):
    spec=EdgeChorusSpec(
        edge_type="research_phrase",
        required_participants=("world_state_bind","triune","settlement"),
        expected_sequence=("world_state_bind","triune","settlement"),
        timing_tolerances_ms={"world_state_bind->triune":(0,5000),"triune->settlement":(0,5000)},
        required_audit_events=("audit_closed",),
        required_state_events=("edge_settled",),
        settlement_timeout_ms=15000,
    )
    if consonant:
        obs=EdgeChorusObservation(
            action_id="a1",edge_type="research_phrase",
            observed_participants=("world_state_bind","triune","settlement"),
            observed_sequence=("world_state_bind","triune","settlement"),
            timestamps_ms={"world_state_bind":1000,"triune":3000,"settlement":6000,"edge_opened":1000,"edge_settled":6000},
            audit_events=("audit_closed",),state_events=("edge_settled",),
        )
    else:
        obs=EdgeChorusObservation(
            action_id="a2",edge_type="research_phrase",
            observed_participants=("world_state_bind",),
            observed_sequence=("world_state_bind",),
            timestamps_ms={"world_state_bind":1000,"edge_opened":1000},
            audit_events=(),state_events=(),
            vns_events=("pulse_instability",),
        )
    return EdgeChorus().score(spec,obs)


def test_temporal_texture_hears_jitter_burstiness_entropy_and_frequency():
    texture=TemporalTexture().score([1000,2000,3000,12000,12500,13000])
    assert texture.sample_size == 5
    assert 0.0 <= texture.jitter_norm <= 1.0
    assert 0.0 <= texture.burstiness <= 1.0
    assert 0.0 <= texture.entropy_signature <= 1.0
    assert texture.dominant_frequency_hz > 0.0
    assert texture.execution_eligible is False


def test_edge_chorus_harmony_distinguishes_consonant_and_fractured_phrases():
    good=_edge(True)
    bad=_edge(False)
    assert good.chorus_quality > bad.chorus_quality
    assert good.resolution_class == "consonant"
    assert bad.resolution_class in {"dissonant","fractured","strained"}
    assert bad.execution_eligible is False


def test_queen_hears_temporal_texture_and_edge_chorus_together():
    acc=_music((1000,2000,3000,12000,12500,13000))
    motif=acc.score("motif-p")
    ent=PolyphonicEntrainment().score(hypothesis_id="motif-p",notes=acc.notes("motif-p"))
    texture=TemporalTexture().score([n.observed_at_ms for n in acc.notes("motif-p")])
    edge=_edge(False)

    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-p",notes=acc.notes("motif-p"),
        motif=motif,entrainment=ent,epoch=_epoch(),
        temporal_texture=texture,edge_chorus=edge,
        now_ms=20000,world_state_id=WS_ID,world_state_hash=WS_HASH,
    )
    assert receipt.temporal_jitter == texture.jitter_norm
    assert receipt.temporal_burstiness == texture.burstiness
    assert receipt.edge_chorus_quality == edge.chorus_quality
    assert "REHEARSE_EDGE_CHORUS" in receipt.conducting_gestures
    assert any(t.notation == "REHEARSE_EDGE_RESOLUTION" for t in receipt.notation_tokens)
    assert receipt.execution_eligible is False


def test_triune_score_sheets_hear_timing_and_edge_harmony():
    acc=_music((1000,2000,3000,12000,12500,13000))
    motif=acc.score("motif-p")
    ent=PolyphonicEntrainment().score(hypothesis_id="motif-p",notes=acc.notes("motif-p"))
    texture=TemporalTexture().score([n.observed_at_ms for n in acc.notes("motif-p")])
    edge=_edge(False)

    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-p",notes=acc.notes("motif-p"),
        motif=motif,entrainment=ent,epoch=_epoch(),
        temporal_texture=texture,edge_chorus=edge,
        now_ms=20000,world_state_id=WS_ID,world_state_hash=WS_HASH,
    )
    metatron=next(s for s in receipt.triune_scores if s.mind=="METATRON")
    michael=next(s for s in receipt.triune_scores if s.mind=="MICHAEL")
    loki=next(s for s in receipt.triune_scores if s.mind=="LOKI")
    assert any("edge_chorus:" in x for x in metatron.motifs_heard)
    assert any("timing_jitter:" in x for x in michael.cautions)
    assert any("edge_resolution:" in x for x in loki.cautions)
