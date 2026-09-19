from __future__ import annotations

import pytest

from strategies.relative_value_lab.vns_score_conductor import VNSScoreConductor
from strategies.relative_value_lab.vns_score_stream import VNSScoreStream


def candidate(
    *,
    symbol="BTC/USD",
    ts=1000,
    price=100.0,
    spread=5.0,
    depth=100000.0,
    quality=1.0,
):
    return {
        "symbol":symbol,
        "venue":"kraken",
        "timestamp_ms":ts,
        "price":price,
        "quote_volume_24h":50_000_000.0,
        "spread_bps":spread,
        "depth_usd_25bps":depth,
        "listing_age_days":1000.0,
        "venue_count":1,
        "data_quality":quality,
        "freshness_sec":1.0,
        "continuity_ratio":1.0,
        "observation_eligible":True,
        "values":{
            "market_world_state_crystal":{
                "world_state_id":"c"*64,
                "spread_bps":spread,
                "depth_usd_25bps":depth,
                "quote_volume_24h":50_000_000.0,
                "data_quality":quality,
                "freshness_sec":1.0,
                "continuity_ratio":1.0,
                "volatility_expansion":1.2,
                "orderbook_digest":"book",
                "instrument_metadata_digest":"instrument",
                "exchange_status":"active",
                "fresh_until_ms":ts+180000,
            }
        },
    }


def cycle(run_id,completed,candidates):
    return {
        "phase":1,
        "mode":"observation_only",
        "run":{"run_id":run_id,"venue":"kraken","completed_at_ms":completed},
        "status":"HEALTHY",
        "candidates":list(candidates),
        "world_state_summary":{"fresh_candidate_count":len(candidates),"venue":"kraken"},
        "dataset_hash":"dataset-"+run_id,
        "execution_wired":False,
        "orders_submitted":0,
    }


def measure(conductor,run_id,completed,**kwargs):
    return conductor.conduct_cycle(
        cycle(run_id,completed,[candidate(ts=completed-100,**kwargs)])
    )


def test_score_stream_cold_start_is_rest():
    stream=VNSScoreStream()
    phrase=stream.phrase()
    assert phrase.measure_count==0
    assert phrase.rest_density==1.0
    assert phrase.execution_eligible is False
    assert phrase.promotion_eligible is False


def test_first_measure_is_a_rest_when_no_vns_change_exists():
    conductor=VNSScoreConductor(pulse_floor=.01)
    stream=VNSScoreStream()
    phrase=stream.append(measure(conductor,"r1",1100,price=100.0))
    assert phrase.measure_count==1
    assert phrase.pulse_density==0.0
    assert phrase.rest_density==1.0


def test_repeated_similar_accent_can_become_echo_pressure():
    conductor=VNSScoreConductor(pulse_floor=.001)
    stream=VNSScoreStream()
    stream.append(measure(conductor,"r1",1100,price=100.0,spread=5.0,depth=100000))
    stream.append(measure(conductor,"r2",2100,price=100.5,spread=5.0,depth=100000))
    phrase=stream.append(measure(conductor,"r3",3100,price=101.0,spread=5.0,depth=100000))
    assert phrase.pulse_density>0.0
    assert phrase.pulse_recurrence>0.0
    assert phrase.echo_pressure>=0.0


def test_large_observed_feature_change_raises_measure_novelty():
    conductor=VNSScoreConductor(pulse_floor=.001)
    stream=VNSScoreStream()
    stream.append(measure(conductor,"r1",1100,price=100.0,spread=5.0,depth=100000))
    phrase=stream.append(measure(conductor,"r2",2100,price=120.0,spread=15.0,depth=30000))
    assert phrase.measure_novelty>0.10
    assert phrase.phrase_energy>0.0


def test_scope_change_is_heard_as_attention_churn_not_market_modulation():
    conductor=VNSScoreConductor(pulse_floor=.01)
    stream=VNSScoreStream()
    first=conductor.conduct_cycle(
        cycle("r1",1100,[candidate(symbol="BTC/USD",ts=1000)])
    )
    second=conductor.conduct_cycle(
        cycle("r2",2100,[candidate(symbol="ETH/USD",ts=2000,price=50.0)])
    )
    stream.append(first)
    phrase=stream.append(second)
    assert phrase.attention_churn>0.0
    assert phrase.source_churn>0.0
    assert phrase.modulation==0.0


def test_increasing_pulse_energy_creates_crescendo():
    conductor=VNSScoreConductor(pulse_floor=.001)
    stream=VNSScoreStream()
    stream.append(measure(conductor,"r1",1100,price=100.0))
    stream.append(measure(conductor,"r2",2100,price=100.1))
    stream.append(measure(conductor,"r3",3100,price=103.0))
    phrase=stream.append(measure(conductor,"r4",4100,price=108.0))
    assert phrase.crescendo>=phrase.decrescendo
    assert phrase.phrase_energy>0.0


def test_out_of_order_measure_is_refused():
    conductor=VNSScoreConductor()
    stream=VNSScoreStream()
    newer=measure(conductor,"new",3100,price=101.0)
    older=measure(VNSScoreConductor(),"old",2100,price=100.0)
    stream.append(newer)
    with pytest.raises(ValueError,match="time_reversal"):
        stream.append(older)


def test_duplicate_measure_is_idempotent():
    conductor=VNSScoreConductor()
    stream=VNSScoreStream()
    row=measure(conductor,"r1",1100,price=100.0)
    first=stream.append(row)
    second=stream.append(row)
    assert first.measure_count==1
    assert second.measure_count==1
    assert first.phrase_id==second.phrase_id

def test_same_scope_feature_change_is_heard_as_modulation():
    conductor=VNSScoreConductor(pulse_floor=.001)
    stream=VNSScoreStream()
    first=conductor.conduct_cycle(
        cycle("r1",1100,[candidate(symbol="BTC/USD",ts=1000,price=100.0,spread=5.0,depth=100000)])
    )
    second=conductor.conduct_cycle(
        cycle("r2",2100,[candidate(symbol="BTC/USD",ts=2000,price=108.0,spread=9.0,depth=60000)])
    )
    stream.append(first)
    phrase=stream.append(second)
    assert phrase.attention_churn==0.0
    assert phrase.modulation>0.0
