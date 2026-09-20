from strategies.relative_value_lab.attention_queen_assembly import (
    assemble_attention_channels,
)
from strategies.relative_value_lab.causal_cascade import (
    CascadeEvent,
    CascadeLink,
    CausalCascade,
)
from strategies.relative_value_lab.colony_correlation import (
    ColonyCorrelator,
    CorrelationEvent,
)
from strategies.relative_value_lab.hive_pulse import HivePulseEngine
from strategies.relative_value_lab.market_hunting import (
    HuntObservation,
    MotifHunter,
)
from strategies.relative_value_lab.queen_input_assembly import (
    assemble_queen_inputs,
)
from strategies.relative_value_lab.vns_score_conductor import (
    VNSScoreConductor,
)
from strategies.relative_value_lab.world_graph import WorldGraph


def cycle():
    return {
        "run": {
            "run_id": "r1",
            "venue": "kraken",
            "completed_at_ms": 3000,
        },
        "candidates": [{
            "symbol": "BTC/USD",
            "venue": "kraken",
            "timestamp_ms": 2900,
            "price": 100.0,
            "spread_bps": 5.0,
            "depth_usd_25bps": 100000.0,
            "quote_volume_24h": 50000000.0,
            "data_quality": 1.0,
            "freshness_sec": 1.0,
            "continuity_ratio": 1.0,
            "observation_eligible": True,
        }],
        "world_state_summary": {"fresh_candidate_count": 1},
        "dataset_hash": "dataset-r1",
    }


def fixtures(frame):
    r1 = "sha256:" + "1" * 64
    r2 = "sha256:" + "2" * 64
    rm = "sha256:" + "3" * 64

    hunt_obs = HuntObservation(
        observation_id="hunt-observation",
        timestamp_ms=2500,
        scope="pair:BTC/USD",
        pair_id="BTC/USD",
        asset_ids=("BTC", "USD"),
        venue="kraken",
        family="microstructure",
        features={
            "abs_spread_zscore": 2.5,
            "flow_exhaustion": .7,
            "relationship_stability": .8,
        },
        evidence_root=r1,
        world_state_id=frame.world_state_id,
        world_state_hash=frame.world_state_hash,
    )

    hunts = MotifHunter().hunt((hunt_obs,))

    correlation_events = (
        CorrelationEvent(
            event_id="e1",
            timestamp_ms=2200,
            scope="pair:BTC/USD",
            pair_id="BTC/USD",
            asset_ids=("BTC", "USD"),
            venue="kraken",
            feature_family="microstructure",
            hypothesis_family="reversal",
            lineage_root="lineage-a",
            evidence_root=r1,
        ),
        CorrelationEvent(
            event_id="e2",
            timestamp_ms=2500,
            scope="pair:BTC/USDT",
            pair_id="BTC/USDT",
            asset_ids=("BTC", "USDT"),
            venue="kraken",
            feature_family="structural",
            hypothesis_family="reversal",
            lineage_root="lineage-b",
            evidence_root=r2,
        ),
    )

    correlations = ColonyCorrelator(
        temporal_window_ms=5000
    ).correlate(correlation_events)

    cascade_events = (
        CascadeEvent(
            event_id="c1",
            timestamp_ms=2200,
            event_class="aggressor_sell_burst",
            scope="pair:BTC/USD",
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            evidence_root=r1,
            family="microstructure",
            lineage_root="lineage-a",
            pair_id="BTC/USD",
            asset_ids=("BTC", "USD"),
        ),
        CascadeEvent(
            event_id="c2",
            timestamp_ms=2500,
            event_class="depth_depletion",
            scope="pair:BTC/USD",
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            evidence_root=r2,
            family="structural",
            lineage_root="lineage-b",
            pair_id="BTC/USD",
            asset_ids=("BTC", "USD"),
        ),
    )

    cascade_links = (
        CascadeLink(
            source_event_id="c1",
            target_event_id="c2",
            mechanism="sell_pressure_to_depth_depletion",
            mechanism_evidence_root=rm,
            confidence=.8,
        ),
    )

    cascade = CausalCascade().build(
        events=cascade_events,
        links=cascade_links,
    )

    pulse = HivePulseEngine.from_cascade(
        cascade,
        pulse_class="SEARCH_PULSE",
        scope="pair:BTC/USD",
        issued_at_ms=2600,
        ttl_ms=10000,
        lineage_root="lineage-a",
        evidence_root=r1,
    )

    return (
        hunts,
        correlation_events,
        correlations,
        cascade_events,
        cascade_links,
        cascade,
        (pulse,),
    )


def test_attention_channels_present_and_traceable():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    (
        hunts,
        corr_events,
        correlations,
        cascade_events,
        cascade_links,
        cascade,
        pulses,
    ) = fixtures(measure.frame)

    channels, nodes = assemble_attention_channels(
        graph,
        hunt_matches=hunts,
        correlations=correlations,
        correlation_events=corr_events,
        cascade=cascade,
        cascade_events=cascade_events,
        cascade_links=cascade_links,
        hive_pulses=pulses,
        created_at_ms=3100,
    )

    assembly = assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=channels,
    )

    expected = {
        "MARKET_HUNTING",
        "COLONY_CORRELATION",
        "CAUSAL_CASCADE",
        "HIVE_PULSE",
    }

    assert expected.issubset(set(assembly.present_channels))
    assert len(nodes) == 4

    for name in expected:
        item = next(x for x in assembly.channels if x.name == name)
        assert item.source_node_ids
        assert item.source_receipt_ids


def test_correlation_remains_noncausal():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    (
        _,
        corr_events,
        correlations,
        *_,
    ) = fixtures(measure.frame)

    channels, nodes = assemble_attention_channels(
        graph,
        correlations=correlations,
        correlation_events=corr_events,
        created_at_ms=3100,
    )

    assert channels["COLONY_CORRELATION"].state == "PRESENT"

    node = next(
        x for x in nodes
        if x.family == "COLONY_CORRELATION"
    )

    assert node.payload["causal_claim"] is False
    assert all(
        receipt["causal_claim"] is False
        for receipt in node.payload["correlations"]
    )


def test_cascade_remains_supported_propagation_not_causal_proof():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    (
        _,
        _,
        _,
        cascade_events,
        cascade_links,
        cascade,
        _,
    ) = fixtures(measure.frame)

    channels, nodes = assemble_attention_channels(
        graph,
        cascade=cascade,
        cascade_events=cascade_events,
        cascade_links=cascade_links,
        created_at_ms=3100,
    )

    assert channels["CAUSAL_CASCADE"].state == "PRESENT"

    node = next(
        x for x in nodes
        if x.family == "CAUSAL_CASCADE"
    )

    assert node.payload["causal_proof"] is False


def test_positive_hive_pulse_is_attention_only():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    *_, pulses = fixtures(measure.frame)

    channels, nodes = assemble_attention_channels(
        graph,
        hive_pulses=pulses,
        created_at_ms=3100,
    )

    node = next(
        x for x in nodes
        if x.family == "HIVE_PULSE"
    )

    payload = node.payload["pulses"][0]

    assert payload["authority_effect"] == "ATTENTION_ONLY"
    assert payload["execution_eligible"] is False
    assert payload["promotion_eligible"] is False


def test_missing_cascade_is_not_applicable_not_zero():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    channels, _ = assemble_attention_channels(
        graph,
        created_at_ms=3100,
    )

    assert channels["CAUSAL_CASCADE"].state == "NOT_APPLICABLE"


def test_correlation_without_events_is_error():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    (
        _,
        _,
        correlations,
        *_,
    ) = fixtures(measure.frame)

    channels, _ = assemble_attention_channels(
        graph,
        correlations=correlations,
        correlation_events=(),
        created_at_ms=3100,
    )

    assert channels["COLONY_CORRELATION"].state == "ERROR"


def test_disabling_hive_pulse_changes_only_hive_pulse():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    (
        hunts,
        corr_events,
        correlations,
        cascade_events,
        cascade_links,
        cascade,
        pulses,
    ) = fixtures(measure.frame)

    channels, _ = assemble_attention_channels(
        graph,
        hunt_matches=hunts,
        correlations=correlations,
        correlation_events=corr_events,
        cascade=cascade,
        cascade_events=cascade_events,
        cascade_links=cascade_links,
        hive_pulses=pulses,
        created_at_ms=3100,
        disabled=frozenset({"HIVE_PULSE"}),
    )

    assert channels["HIVE_PULSE"].state == "DISABLED_BY_MASK"
    assert channels["MARKET_HUNTING"].state == "PRESENT"
    assert channels["COLONY_CORRELATION"].state == "PRESENT"
    assert channels["CAUSAL_CASCADE"].state == "PRESENT"
