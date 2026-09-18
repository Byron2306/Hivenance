from __future__ import annotations

from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.evaluation import WalkForwardPrediction
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.harmonic_governance import HarmonicForecastGovernance
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.polyphonic_resonance import PolyphonicResonance
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS="ws-rq"
WH="sha256:"+"a"*64
STRUCT="sha256:"+"1"*64
STAT="sha256:"+"2"*64


def pred(model,horizon,value):
    return WalkForwardPrediction(
        schema="hivenance_relative_value_walk_forward_prediction_v1",
        example_id=f"{model}-{horizon}",
        pair_id="A/USD__B/USD",
        timestamp_ms=1000,
        horizon_seconds=horizon,
        model_id=model,
        predicted_signed_bps=value,
        realized_signed_bps=1.0,
        directional_gross_bps=1.0,
        spread_cost_proxy_bps=1.0,
        directional_after_spread_proxy_bps=0.0,
        train_samples=100,
    )


def build():
    reg=LineageRegistry([
        BeeLineage(STRUCT,"structural",STRUCT),
        BeeLineage(STAT,"statistical",STAT),
    ])
    bus=WaggleProtocol(registry=reg)
    acc=MusicalMotifAccumulator(registry=reg)
    rows=[
        ("s","structural",STRUCT,1000,10,"LONG_A_SHORT_B"),
        ("t","statistical",STAT,6000,10,"LONG_A_SHORT_B"),
        ("s2","structural",STRUCT,11000,120,"LONG_B_SHORT_A"),
        ("t2","statistical",STAT,16000,120,"LONG_B_SHORT_A"),
    ]
    for bee,fam,lin,ts,horizon,direction in rows:
        msg=bus.build_message(
            bee_id=bee,family=fam,lineage_digest=lin,
            message_type="WAGGLE" if ts==1000 else "FOLLOW",
            scope="A/USD__B/USD",hypothesis_id="motif-rq",
            world_state_id=WS,world_state_hash=WH,observed_at_ms=ts,
            evidence_root="sha256:"+bee[0]*64,horizon_seconds=horizon,
            direction=direction,expected_move_bps=2.0,uncertainty=.2,
            independent_claimed=True,
        )
        rec=bus.publish(msg,current_world_state_id=WS,current_world_state_hash=WH,now_ms=ts)
        acc.ingest(message=msg,receipt=rec)

    harmonic=HarmonicForecastGovernance().score(
        pair_id="A/USD__B/USD",timestamp_ms=1000,
        predictions=[
            pred("relative_value_ou_mean_reversion_v1",10,3.0),
            pred("relative_value_expanding_ridge_v1",10,2.0),
            pred("relative_value_ou_mean_reversion_v1",120,-3.0),
            pred("relative_value_expanding_ridge_v1",120,-2.0),
        ],
    )
    ent=PolyphonicEntrainment().score(
        hypothesis_id="motif-rq",notes=acc.notes("motif-rq")
    )
    poly=PolyphonicResonance().score(
        harmonic=harmonic,entrainment=ent,now_ms=1000
    )
    motif=acc.score("motif-rq")
    epoch=ResearchGovernanceEpochService.start_epoch(
        world_state_id=WS,world_state_hash=WH,started_at_ms=0,ttl_ms=120000,
        genre_mode="watchful",strictness_level="standard",scope="relative_value_lab",
    )
    return acc,motif,ent,poly,epoch


def test_queen_conducts_counterpoint_without_collapsing_registers():
    acc,motif,ent,poly,epoch=build()
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-rq",notes=acc.notes("motif-rq"),
        motif=motif,entrainment=ent,epoch=epoch,
        polyphonic_resonance=poly,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    assert receipt.cross_band_tension == poly.cross_band_tension
    assert receipt.resonance_texture == poly.texture
    if poly.texture=="COUNTERPOINT":
        assert "CONDUCT_COUNTERPOINT" in receipt.conducting_gestures
        assert any(t.notation=="PRESERVE_COUNTERPOINT" for t in receipt.notation_tokens)
    loki=next(s for s in receipt.triune_scores if s.mind=="LOKI")
    if poly.cross_band_tension > .55:
        assert "preserve_cross_band_counterpoint" in loki.invitations


def test_queen_global_resonance_surface_has_no_market_direction():
    acc,motif,ent,poly,epoch=build()
    receipt=ConductingQueen().conduct(
        hypothesis_id="motif-rq",notes=acc.notes("motif-rq"),
        motif=motif,entrainment=ent,epoch=epoch,
        polyphonic_resonance=poly,
        now_ms=20000,world_state_id=WS,world_state_hash=WH,
    )
    payload=receipt.to_dict()
    assert "direction" not in payload
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
