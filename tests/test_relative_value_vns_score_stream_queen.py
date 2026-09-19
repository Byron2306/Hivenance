from __future__ import annotations

from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.vns_score_conductor import VNSScoreConductor
from strategies.relative_value_lab.vns_score_stream import VNSScoreStream
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


STRUCT="sha256:"+"1"*64
STAT="sha256:"+"2"*64


def cycle(run_id,completed,price,spread=5.0,depth=100000.0):
    return {
        "phase":1,
        "mode":"observation_only",
        "run":{"run_id":run_id,"venue":"kraken","completed_at_ms":completed},
        "status":"HEALTHY",
        "candidates":[{
            "symbol":"BTC/USD",
            "venue":"kraken",
            "timestamp_ms":completed-100,
            "price":price,
            "quote_volume_24h":50_000_000.0,
            "spread_bps":spread,
            "depth_usd_25bps":depth,
            "listing_age_days":1000.0,
            "venue_count":1,
            "data_quality":1.0,
            "freshness_sec":1.0,
            "continuity_ratio":1.0,
            "observation_eligible":True,
            "values":{
                "market_world_state_crystal":{
                    "world_state_id":"c"*64,
                    "spread_bps":spread,
                    "depth_usd_25bps":depth,
                    "quote_volume_24h":50_000_000.0,
                    "data_quality":1.0,
                    "freshness_sec":1.0,
                    "continuity_ratio":1.0,
                    "volatility_expansion":1.1,
                    "orderbook_digest":"book",
                    "instrument_metadata_digest":"instrument",
                    "exchange_status":"active",
                    "fresh_until_ms":completed+180000,
                }
            },
        }],
        "world_state_summary":{"fresh_candidate_count":1,"venue":"kraken"},
        "dataset_hash":"dataset-"+run_id,
        "execution_wired":False,
        "orders_submitted":0,
    }


def music(frame):
    reg=LineageRegistry([
        BeeLineage(STRUCT,"structural",STRUCT),
        BeeLineage(STAT,"statistical",STAT),
    ])
    bus=WaggleProtocol(registry=reg)
    acc=MusicalMotifAccumulator(registry=reg)
    for bee,fam,lin,ts in [
        ("s","structural",STRUCT,1000),
        ("t","statistical",STAT,2000),
    ]:
        msg=bus.build_message(
            bee_id=bee,family=fam,lineage_digest=lin,
            message_type="WAGGLE" if bee=="s" else "FOLLOW",
            scope="BTC/USD",hypothesis_id="motif-stream",
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            observed_at_ms=ts,
            evidence_root="sha256:"+bee[0]*64,
            horizon_seconds=10,direction="LONG_A_SHORT_B",
            expected_move_bps=1.0,uncertainty=.2,independent_claimed=True,
        )
        rec=bus.publish(
            msg,current_world_state_id=frame.world_state_id,
            current_world_state_hash=frame.world_state_hash,now_ms=ts,
        )
        acc.ingest(message=msg,receipt=rec)
    motif=acc.score("motif-stream")
    ent=PolyphonicEntrainment().score(
        hypothesis_id="motif-stream",notes=acc.notes("motif-stream")
    )
    return acc,motif,ent


def test_queen_hears_vns_phrase_crescendo():
    conductor=VNSScoreConductor(pulse_floor=.001)
    stream=VNSScoreStream()
    rows=[
        conductor.conduct_cycle(cycle("r1",3000,100.0)),
        conductor.conduct_cycle(cycle("r2",4000,100.1)),
        conductor.conduct_cycle(cycle("r3",5000,103.0)),
        conductor.conduct_cycle(cycle("r4",6000,108.0)),
    ]
    phrase=None
    for row in rows:
        phrase=stream.append(row)

    latest=rows[-1]
    acc,motif,ent=music(latest.frame)
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        latest.frame,started_at_ms=6000,ttl_ms=20000
    )
    receipt=ConductingQueen().conduct_against_frame(
        frame=latest.frame,now_ms=6500,
        hypothesis_id="motif-stream",notes=acc.notes("motif-stream"),
        motif=motif,entrainment=ent,epoch=epoch,
        vns_pulses=latest.pulses,vns_phrase=phrase,
    )
    assert receipt.vns_phrase_energy==phrase.phrase_energy
    assert receipt.vns_measure_novelty==phrase.measure_novelty
    if phrase.crescendo>phrase.decrescendo:
        assert "SHAPE_VNS_PHRASE_CRESCENDO" in receipt.conducting_gestures
    assert receipt.execution_eligible is False


def test_queen_hears_vns_rest_without_inventing_signal():
    conductor=VNSScoreConductor(pulse_floor=.5)
    stream=VNSScoreStream()
    rows=[
        conductor.conduct_cycle(cycle("r1",3000,100.0)),
        conductor.conduct_cycle(cycle("r2",4000,100.0)),
        conductor.conduct_cycle(cycle("r3",5000,100.0)),
    ]
    for row in rows:
        phrase=stream.append(row)

    latest=rows[-1]
    acc,motif,ent=music(latest.frame)
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        latest.frame,started_at_ms=5000,ttl_ms=20000
    )
    receipt=ConductingQueen().conduct_against_frame(
        frame=latest.frame,now_ms=5500,
        hypothesis_id="motif-stream",notes=acc.notes("motif-stream"),
        motif=motif,entrainment=ent,epoch=epoch,
        vns_pulses=latest.pulses,vns_phrase=phrase,
    )
    assert phrase.rest_density>0.65
    assert "HEAR_VNS_REST" in receipt.conducting_gestures
    assert receipt.vns_pulse_energy==0.0


def test_vns_phrase_never_grants_authority():
    conductor=VNSScoreConductor(pulse_floor=.001)
    stream=VNSScoreStream()
    first=conductor.conduct_cycle(cycle("r1",3000,100.0))
    second=conductor.conduct_cycle(cycle("r2",4000,110.0,spread=15.0,depth=30000.0))
    stream.append(first)
    phrase=stream.append(second)

    acc,motif,ent=music(second.frame)
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        second.frame,started_at_ms=4000,ttl_ms=20000
    )
    receipt=ConductingQueen().conduct_against_frame(
        frame=second.frame,now_ms=4500,
        hypothesis_id="motif-stream",notes=acc.notes("motif-stream"),
        motif=motif,entrainment=ent,epoch=epoch,
        vns_pulses=second.pulses,vns_phrase=phrase,
    )
    assert phrase.execution_eligible is False
    assert phrase.promotion_eligible is False
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
