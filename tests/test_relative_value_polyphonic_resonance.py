from __future__ import annotations

from strategies.relative_value_lab.evaluation import WalkForwardPrediction
from strategies.relative_value_lab.harmonic_governance import HarmonicForecastGovernance
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.polyphonic_resonance import PolyphonicResonance
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


STRUCT="sha256:"+"1"*64
STAT="sha256:"+"2"*64
WS="ws-poly"
WH="sha256:"+"a"*64


def prediction(model_id,horizon,predicted,ts=1000):
    return WalkForwardPrediction(
        schema="hivenance_relative_value_walk_forward_prediction_v1",
        example_id=f"{model_id}-{horizon}-{ts}",
        pair_id="A/USD__B/USD",
        timestamp_ms=ts,
        horizon_seconds=horizon,
        model_id=model_id,
        predicted_signed_bps=predicted,
        realized_signed_bps=1.0,
        directional_gross_bps=1.0,
        spread_cost_proxy_bps=1.0,
        directional_after_spread_proxy_bps=0.0,
        train_samples=100,
    )


def entrainment():
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
            bee_id=bee,family=fam,lineage_digest=lin,message_type="WAGGLE" if ts==1000 else "FOLLOW",
            scope="A/USD__B/USD",hypothesis_id="motif-poly",
            world_state_id=WS,world_state_hash=WH,observed_at_ms=ts,
            evidence_root="sha256:"+bee[0]*64,horizon_seconds=horizon,
            direction=direction,expected_move_bps=2.0,uncertainty=.2,independent_claimed=True,
        )
        rec=bus.publish(msg,current_world_state_id=WS,current_world_state_hash=WH,now_ms=ts)
        acc.ingest(message=msg,receipt=rec)
    return PolyphonicEntrainment().score(hypothesis_id="motif-poly",notes=acc.notes("motif-poly"))


def harmonic():
    rows=[
        prediction("relative_value_ou_mean_reversion_v1",10,3.0),
        prediction("relative_value_expanding_ridge_v1",10,2.0),
        prediction("relative_value_ou_mean_reversion_v1",120,-3.0),
        prediction("relative_value_expanding_ridge_v1",120,-2.0),
    ]
    return HarmonicForecastGovernance().score(
        pair_id="A/USD__B/USD",timestamp_ms=1000,predictions=rows
    )


def test_polyphonic_resonance_has_no_global_direction():
    receipt=PolyphonicResonance().score(
        harmonic=harmonic(),entrainment=entrainment(),now_ms=1000
    )
    payload=receipt.to_dict()
    assert "direction" not in payload
    assert all("direction" not in r for r in payload["register_resonances"])


def test_opposite_horizon_directions_survive_as_counterpoint():
    h=harmonic()
    poly=PolyphonicResonance().score(harmonic=h,entrainment=entrainment(),now_ms=1000)
    dirs={
        horizon:direction
        for reg in poly.register_resonances
        for horizon,direction in reg.horizon_directions
    }
    assert dirs[10]=="LONG_A_SHORT_B"
    assert dirs[120]=="LONG_B_SHORT_A"
    assert poly.cross_band_tension > 0.0
    assert any(rel.relation=="contrary" for rel in poly.relationships)


def test_register_resonance_preserves_micro_and_macro():
    poly=PolyphonicResonance().score(
        harmonic=harmonic(),entrainment=entrainment(),now_ms=1000
    )
    bands={r.band for r in poly.register_resonances}
    assert bands=={"micro","macro"}
    assert poly.register_diversity > 0.0
    assert poly.global_resonance > 0.0
    assert poly.execution_eligible is False


def test_counterpoint_can_still_be_resonant():
    poly=PolyphonicResonance().score(
        harmonic=harmonic(),entrainment=entrainment(),now_ms=1000
    )
    assert poly.cross_band_tension > 0.0
    assert poly.global_resonance > 0.0
    assert poly.texture in {"COUNTERPOINT","POLYPHONIC","SUSPENDED","FULL_CHORD"}


def test_global_resonance_drift_is_temporal_not_directional():
    engine=PolyphonicResonance()
    h=harmonic()
    e=entrainment()
    first=engine.score(harmonic=h,entrainment=e,now_ms=1000)
    for _ in range(4):
        later=engine.score(harmonic=h,entrainment=e,now_ms=1000)
    assert first.resonance_drift == 0.0
    assert later.resonance_drift >= 0.0
    assert "direction" not in later.to_dict()
