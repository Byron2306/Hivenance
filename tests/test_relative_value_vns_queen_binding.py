from __future__ import annotations

import pytest

from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.vns_score_conductor import VNSScoreConductor
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


STRUCT="sha256:"+"1"*64
STAT="sha256:"+"2"*64


def cycle(run_id,completed,price):
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
            "spread_bps":5.0,
            "depth_usd_25bps":100_000.0,
            "listing_age_days":1000.0,
            "venue_count":1,
            "data_quality":1.0,
            "freshness_sec":1.0,
            "continuity_ratio":1.0,
            "observation_eligible":True,
            "values":{
                "market_world_state_crystal":{
                    "world_state_id":"c"*64,
                    "spread_bps":5.0,
                    "depth_usd_25bps":100_000.0,
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
    rows=[
        ("s","structural",STRUCT,1000),
        ("t","statistical",STAT,2000),
    ]
    for bee,fam,lin,ts in rows:
        msg=bus.build_message(
            bee_id=bee,
            family=fam,
            lineage_digest=lin,
            message_type="WAGGLE" if bee=="s" else "FOLLOW",
            scope="BTC/USD",
            hypothesis_id="motif-frame",
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            observed_at_ms=ts,
            evidence_root="sha256:"+bee[0]*64,
            horizon_seconds=10,
            direction="LONG_A_SHORT_B",
            expected_move_bps=1.0,
            uncertainty=.2,
            independent_claimed=True,
        )
        rec=bus.publish(
            msg,
            current_world_state_id=frame.world_state_id,
            current_world_state_hash=frame.world_state_hash,
            now_ms=ts,
        )
        acc.ingest(message=msg,receipt=rec)

    motif=acc.score("motif-frame")
    ent=PolyphonicEntrainment().score(
        hypothesis_id="motif-frame",notes=acc.notes("motif-frame")
    )
    return acc,motif,ent


def test_queen_conducts_against_concrete_frame_binding():
    measure=VNSScoreConductor().conduct_cycle(cycle("r1",3000,100.0))
    acc,motif,ent=music(measure.frame)
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        measure.frame,started_at_ms=3000,ttl_ms=10000
    )
    receipt=ConductingQueen().conduct_against_frame(
        frame=measure.frame,
        now_ms=3500,
        hypothesis_id="motif-frame",
        notes=acc.notes("motif-frame"),
        motif=motif,
        entrainment=ent,
        epoch=epoch,
        vns_pulses=measure.pulses,
    )
    assert receipt.world_state_tension==0.0
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_queen_frame_wrapper_rejects_manual_binding_override():
    measure=VNSScoreConductor().conduct_cycle(cycle("r1",3000,100.0))
    acc,motif,ent=music(measure.frame)
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        measure.frame,started_at_ms=3000,ttl_ms=10000
    )
    with pytest.raises(ValueError,match="owns_world_binding"):
        ConductingQueen().conduct_against_frame(
            frame=measure.frame,
            now_ms=3500,
            hypothesis_id="motif-frame",
            notes=acc.notes("motif-frame"),
            motif=motif,
            entrainment=ent,
            epoch=epoch,
            world_state_id="ws-wrong",
        )


def test_stale_frame_remains_audible_as_world_state_tension():
    measure=VNSScoreConductor(freshness_window_ms=1000).conduct_cycle(
        cycle("r1",3000,100.0)
    )
    acc,motif,ent=music(measure.frame)
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        measure.frame,started_at_ms=3000,ttl_ms=100000
    )
    receipt=ConductingQueen().conduct_against_frame(
        frame=measure.frame,
        now_ms=measure.frame.expires_at_ms+1,
        hypothesis_id="motif-frame",
        notes=acc.notes("motif-frame"),
        motif=motif,
        entrainment=ent,
        epoch=epoch,
    )
    assert receipt.world_state_tension>0.0
    assert "LISTEN_CONTINUOUSLY" in receipt.conducting_gestures
    assert receipt.execution_eligible is False
