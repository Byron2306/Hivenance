from __future__ import annotations

from strategies.relative_value_lab.vns_score_conductor import VNSScoreConductor


def candidate(
    *,
    symbol="BTC/USD",
    ts=1000,
    price=100.0,
    spread=5.0,
    depth=100000.0,
    forecast_direction="UP",
):
    crystal_id="c"*64
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
        "data_quality":1.0,
        "freshness_sec":1.0,
        "continuity_ratio":1.0,
        "observation_eligible":True,
        "values":{
            "forecast":{"direction":forecast_direction,"expected_move_bps":99.0},
            "regime_inputs":{"regime_hint":"trend_expansion"},
            "market_world_state_crystal":{
                "world_state_id":crystal_id,
                "spread_bps":spread,
                "depth_usd_25bps":depth,
                "quote_volume_24h":50_000_000.0,
                "data_quality":1.0,
                "freshness_sec":1.0,
                "continuity_ratio":1.0,
                "volatility_expansion":1.2,
                "orderbook_digest":"book",
                "instrument_metadata_digest":"instrument",
                "exchange_status":"active",
                "fresh_until_ms":ts+180000,
                "regime_hint":"trend_expansion",
            },
        },
    }


def cycle(run_id,completed,candidates):
    return {
        "phase":1,
        "mode":"observation_only",
        "run":{
            "run_id":run_id,
            "venue":"kraken",
            "completed_at_ms":completed,
        },
        "status":"HEALTHY",
        "candidates":list(candidates),
        "world_state_summary":{
            "fresh_candidate_count":len(candidates),
            "venue":"kraken",
        },
        "dataset_hash":"dataset-"+run_id,
        "execution_wired":False,
        "orders_submitted":0,
    }


def test_first_measure_builds_frame_without_hallucinating_change_pulse():
    conductor=VNSScoreConductor()
    measure=conductor.conduct_cycle(
        cycle("run-1",1100,[candidate(ts=1000)])
    )
    assert measure.frame.observation_count==1
    assert measure.pulses==()
    assert measure.execution_eligible is False
    assert measure.promotion_eligible is False


def test_observed_score_excludes_embedded_forecast_and_regime_interpretation():
    conductor=VNSScoreConductor()
    measure=conductor.conduct_cycle(
        cycle("run-1",1100,[candidate(ts=1000,forecast_direction="MOON")])
    )
    payload=measure.frame.observations[0].payload
    raw=str(payload)
    assert "forecast" not in payload
    assert "hypothesis" not in payload
    assert "regime_hint" not in payload
    assert "MOON" not in raw
    assert "trend_expansion" not in raw


def test_second_measure_emits_bound_pulse_from_observed_delta():
    conductor=VNSScoreConductor(pulse_floor=.01)
    first=conductor.conduct_cycle(
        cycle("run-1",1100,[candidate(ts=1000,price=100.0,spread=5.0,depth=100000)])
    )
    second=conductor.conduct_cycle(
        cycle("run-2",2100,[candidate(ts=2000,price=102.0,spread=7.0,depth=70000)])
    )
    assert first.pulses==()
    assert len(second.pulses)==1
    pulse=second.pulses[0]
    assert pulse.world_state_id==second.frame.world_state_id
    assert pulse.world_state_hash==second.frame.world_state_hash
    assert pulse.amplitude>0.0
    assert pulse.execution_eligible is False
    assert pulse.promotion_eligible is False


def test_forecast_change_alone_cannot_create_vns_pulse():
    conductor=VNSScoreConductor(pulse_floor=.01)
    conductor.conduct_cycle(
        cycle("run-1",1100,[candidate(ts=1000,forecast_direction="UP")])
    )
    second=conductor.conduct_cycle(
        cycle("run-2",2100,[candidate(ts=2000,forecast_direction="DOWN")])
    )
    assert second.pulses==()


def test_same_cycle_bytes_produce_same_frame_binding_in_fresh_conductors():
    payload=cycle("run-1",1100,[candidate(ts=1000)])
    a=VNSScoreConductor().conduct_cycle(payload)
    b=VNSScoreConductor().conduct_cycle(payload)
    assert a.frame.world_state_id==b.frame.world_state_id
    assert a.frame.world_state_hash==b.frame.world_state_hash
    assert a.frame.observed_digest==b.frame.observed_digest


def test_multi_symbol_measure_preserves_source_and_scope_inventory():
    measure=VNSScoreConductor().conduct_cycle(
        cycle(
            "run-1",
            1100,
            [
                candidate(symbol="BTC/USD",ts=1000),
                candidate(symbol="ETH/USD",ts=1010,price=50.0),
            ],
        )
    )
    assert measure.candidate_count==2
    assert set(measure.frame.scopes)=={"symbol:BTC/USD","symbol:ETH/USD"}
    assert len(measure.frame.sources)==2
