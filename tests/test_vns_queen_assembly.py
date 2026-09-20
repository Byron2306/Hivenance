from strategies.relative_value_lab.queen_input_assembly import (
    assemble_queen_inputs,
)
from strategies.relative_value_lab.vns_queen_assembly import (
    assemble_vns_channels,
)
from strategies.relative_value_lab.vns_score_conductor import (
    VNSScoreConductor,
)
from strategies.relative_value_lab.vns_score_stream import VNSScoreStream
from strategies.relative_value_lab.world_graph import WorldGraph


def cycle(run_id, completed, price, spread=5.0, depth=100000.0):
    return {
        "phase": 1,
        "mode": "observation_only",
        "run": {
            "run_id": run_id,
            "venue": "kraken",
            "completed_at_ms": completed,
        },
        "status": "HEALTHY",
        "candidates": [{
            "symbol": "BTC/USD",
            "venue": "kraken",
            "timestamp_ms": completed - 100,
            "price": price,
            "quote_volume_24h": 50_000_000.0,
            "spread_bps": spread,
            "depth_usd_25bps": depth,
            "listing_age_days": 1000.0,
            "venue_count": 1,
            "data_quality": 1.0,
            "freshness_sec": 1.0,
            "continuity_ratio": 1.0,
            "observation_eligible": True,
            "values": {
                "market_world_state_crystal": {
                    "world_state_id": "c" * 64,
                    "spread_bps": spread,
                    "depth_usd_25bps": depth,
                    "quote_volume_24h": 50_000_000.0,
                    "data_quality": 1.0,
                    "freshness_sec": 1.0,
                    "continuity_ratio": 1.0,
                    "volatility_expansion": 1.1,
                    "orderbook_digest": "book",
                    "instrument_metadata_digest": "instrument",
                    "exchange_status": "active",
                    "fresh_until_ms": completed + 180000,
                }
            },
        }],
        "world_state_summary": {
            "fresh_candidate_count": 1,
            "venue": "kraken",
        },
        "dataset_hash": "dataset-" + run_id,
        "execution_wired": False,
        "orders_submitted": 0,
    }


def build_vns():
    conductor = VNSScoreConductor(pulse_floor=.001)
    stream = VNSScoreStream()

    first = conductor.conduct_cycle(
        cycle("r1", 3000, 100.0)
    )
    stream.append(first)

    second = conductor.conduct_cycle(
        cycle("r2", 4000, 105.0, spread=12.0, depth=50000.0)
    )
    phrase = stream.append(second)

    return second, phrase


def test_vns_three_channels_are_present_and_traceable():
    measure, phrase = build_vns()

    graph = WorldGraph(measure.frame)

    channels, nodes = assemble_vns_channels(
        graph,
        measure=measure,
        phrase=phrase,
        created_at_ms=4100,
    )

    view = graph.queen_view(created_at_ms=4100)

    assembly = assemble_queen_inputs(
        queen_view=view,
        created_at_ms=4100,
        channels=channels,
    )

    assert {
        "VNS_SENSORY_PULSES",
        "VNS_SCORE_STREAM",
        "TEMPORAL_TEXTURE",
    }.issubset(set(assembly.present_channels))

    assert len(nodes) == 3

    for name in (
        "VNS_SENSORY_PULSES",
        "VNS_SCORE_STREAM",
        "TEMPORAL_TEXTURE",
    ):
        item = next(x for x in assembly.channels if x.name == name)
        assert item.source_node_ids
        assert item.source_receipt_ids


def test_vns_derived_receipts_do_not_multiply_observed_roots():
    measure, phrase = build_vns()

    graph = WorldGraph(measure.frame)

    base_root_count = len({
        obs.evidence_root
        for obs in measure.frame.observations
    })

    assemble_vns_channels(
        graph,
        measure=measure,
        phrase=phrase,
        created_at_ms=4100,
    )

    view = graph.queen_view(created_at_ms=4100)

    assert view.independent_evidence_root_count == base_root_count


def test_vns_pulse_digest_stays_payload_provenance():
    measure, phrase = build_vns()

    graph = WorldGraph(measure.frame)

    _, nodes = assemble_vns_channels(
        graph,
        measure=measure,
        phrase=phrase,
        created_at_ms=4100,
    )

    sensory = next(
        node for node in nodes
        if node.family == "VNS_SENSORY_PULSES"
    )

    if measure.pulses:
        pulse = sensory.payload["pulses"][0]

        assert pulse["derived_evidence_root"].startswith("sha256:")
        assert pulse["derived_evidence_root"] not in sensory.evidence_roots


def test_disabling_vns_stream_changes_only_that_channel():
    measure, phrase = build_vns()

    graph = WorldGraph(measure.frame)

    channels, _ = assemble_vns_channels(
        graph,
        measure=measure,
        phrase=phrase,
        created_at_ms=4100,
        disabled=frozenset({"VNS_SCORE_STREAM"}),
    )

    assert channels["VNS_SCORE_STREAM"].state == "DISABLED_BY_MASK"
    assert channels["VNS_SENSORY_PULSES"].state == "PRESENT"
    assert channels["TEMPORAL_TEXTURE"].state == "PRESENT"


def test_missing_phrase_is_not_silently_zero():
    measure, _ = build_vns()

    graph = WorldGraph(measure.frame)

    channels, _ = assemble_vns_channels(
        graph,
        measure=measure,
        phrase=None,
        created_at_ms=4100,
    )

    assert channels["VNS_SENSORY_PULSES"].state == "PRESENT"
    assert channels["VNS_SCORE_STREAM"].state == "ABSENT_DATA"
    assert channels["TEMPORAL_TEXTURE"].state == "ABSENT_DATA"


def test_vns_world_mismatch_is_refused():
    measure, phrase = build_vns()

    other = VNSScoreConductor().conduct_cycle(
        cycle("other", 5000, 90.0)
    )

    graph = WorldGraph(other.frame)

    try:
        assemble_vns_channels(
            graph,
            measure=measure,
            phrase=phrase,
            created_at_ms=5100,
        )
    except ValueError as exc:
        assert "vns_measure_world_state" in str(exc)
    else:
        raise AssertionError("expected world mismatch refusal")
