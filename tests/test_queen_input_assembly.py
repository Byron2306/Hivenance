import pytest

from strategies.relative_value_lab.queen_input_assembly import (
    REQUIRED_CHANNELS,
    QueenInputChannel,
    assemble_queen_inputs,
    channel,
)
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


def root(ch: str) -> str:
    return "sha256:" + ch * 64


def frame():
    obs = ScoreObservation(
        observation_id="obs-1",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1000,
        evidence_root=root("a"),
        payload={"price": 100.0},
    )

    return CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=1000,
        freshness_window_ms=10000,
    )


def test_missing_channels_become_explicit_absent_data():
    graph = WorldGraph(frame())
    view = graph.queen_view(created_at_ms=1001)

    assembly = assemble_queen_inputs(
        queen_view=view,
        created_at_ms=1001,
        channels={},
    )

    assert len(assembly.channels) == len(REQUIRED_CHANNELS)
    assert assembly.present_channels == ()
    assert set(assembly.absent_channels) == set(REQUIRED_CHANNELS)
    assert assembly.completeness_ratio == 0.0


def test_present_channel_requires_traceable_source():
    with pytest.raises(
        ValueError,
        match="queen_input_present_without_source",
    ):
        QueenInputChannel(
            name="VNS_SENSORY_PULSES",
            state="PRESENT",
            source_node_ids=(),
            source_receipt_ids=(),
            evidence_roots=(),
            payload={"pulse_count": 1},
        )


def test_disabled_channel_is_not_treated_as_absent_market_reading():
    graph = WorldGraph(frame())
    view = graph.queen_view(created_at_ms=1001)

    assembly = assemble_queen_inputs(
        queen_view=view,
        created_at_ms=1001,
        channels={
            "MYSTIQUE_CHALLENGE": channel(
                name="MYSTIQUE_CHALLENGE",
                state="DISABLED_BY_MASK",
                reason="phase7_test_mask",
            )
        },
    )

    assert "MYSTIQUE_CHALLENGE" in assembly.disabled_channels
    assert "MYSTIQUE_CHALLENGE" not in assembly.present_channels


def test_error_channel_is_explicit():
    graph = WorldGraph(frame())
    view = graph.queen_view(created_at_ms=1001)

    assembly = assemble_queen_inputs(
        queen_view=view,
        created_at_ms=1001,
        channels={
            "VNS_SCORE_STREAM": channel(
                name="VNS_SCORE_STREAM",
                state="ERROR",
                reason="stream_receipt_invalid",
            )
        },
    )

    assert "VNS_SCORE_STREAM" in assembly.error_channels


def test_present_channel_preserves_worldgraph_roots():
    graph = WorldGraph(frame())

    node = graph.add_node(
        organ_id="vns",
        family="VNS",
        created_at_ms=1000,
        evidence_roots=(root("a"),),
        lineage_id="vns",
        transformation_id="vns.v1",
        payload={"pulse_count": 2},
    )

    view = graph.queen_view(created_at_ms=1001)

    assembly = assemble_queen_inputs(
        queen_view=view,
        created_at_ms=1001,
        channels={
            "VNS_SENSORY_PULSES": channel(
                name="VNS_SENSORY_PULSES",
                state="PRESENT",
                source_nodes=(node,),
                payload={"pulse_count": 2},
            )
        },
    )

    item = next(
        x for x in assembly.channels
        if x.name == "VNS_SENSORY_PULSES"
    )

    assert item.source_node_ids == (node.node_id,)
    assert item.evidence_roots == (root("a"),)
    assert "VNS_SENSORY_PULSES" in assembly.present_channels


def test_not_applicable_is_explicit_not_zero():
    graph = WorldGraph(frame())
    view = graph.queen_view(created_at_ms=1001)

    assembly = assemble_queen_inputs(
        queen_view=view,
        created_at_ms=1001,
        channels={
            "EDGE_CHORUS": channel(
                name="EDGE_CHORUS",
                state="NOT_APPLICABLE",
                reason="no_governed_edge_open",
            )
        },
    )

    item = next(
        x for x in assembly.channels
        if x.name == "EDGE_CHORUS"
    )

    assert item.state == "NOT_APPLICABLE"
    assert item.payload == {}
