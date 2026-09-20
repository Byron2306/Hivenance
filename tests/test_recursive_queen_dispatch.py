from dataclasses import dataclass

import pytest

from strategies.relative_value_lab.recursive_queen_dispatch import (
    dispatch_challenge,
)
from strategies.relative_value_lab.recursive_queen_loop import (
    build_request,
    observed_root_digest,
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
        "world_state_summary": {
            "fresh_candidate_count": 1,
        },
        "dataset_hash": "r1",
    }


@dataclass(frozen=True)
class Queen:
    receipt_id: str = "queen-1"
    hypothesis_id: str = "motif-1"
    polyphonic_pressure: float = .75
    world_state_tension: float = .05
    hunt_pressure: float = .65
    edge_settlement: float = .70
    temporal_cadence_coherence: float = .80
    timbral_diversity: float = .75
    register_diversity: float = .65
    edge_chorus_quality: float = .80


def setup():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    source = graph.add_node(
        organ_id="test_source",
        family="TEST_SOURCE",
        created_at_ms=3000,
        evidence_roots=tuple(
            obs.evidence_root
            for obs in graph.frame.observations
        ),
        lineage_id="test.source.v1",
        transformation_id="test.source.v1",
        payload={"observed": True},
    )

    request = build_request(
        graph=graph,
        recurrence_index=0,
        request_kind="CHALLENGE",
        target="loki_counterpoint",
        reason="queen_notation:CHALLENGE_CADENCE",
        source_receipt_id="queen-1",
    )

    return graph, source, request


def test_challenge_dispatch_changes_graph_not_observed_root():
    graph, source, request = setup()

    before_root = observed_root_digest(graph)
    before_count = len(
        graph.queen_view(created_at_ms=3000).nodes
    )

    response, node, mystique = dispatch_challenge(
        graph=graph,
        request=request,
        queen_receipt=Queen(),
        source_nodes=(source,),
        created_at_ms=3001,
    )

    after_root = observed_root_digest(graph)
    after_count = len(
        graph.queen_view(created_at_ms=3001).nodes
    )

    assert before_root == after_root
    assert after_count == before_count + 1

    assert response.state == "ANSWERED"
    assert response.graph_changed is True
    assert response.organ_id == "mystique"

    assert node.family == "MYSTIQUE_CHALLENGE"

    assert mystique.prospective_evidence_eligible is False
    assert mystique.contamination_guard_passed is True


def test_synthetic_roots_do_not_enter_graph_evidence_roots():
    graph, source, request = setup()

    _, node, mystique = dispatch_challenge(
        graph=graph,
        request=request,
        queen_receipt=Queen(),
        source_nodes=(source,),
        created_at_ms=3001,
    )

    for root in mystique.synthetic_evidence_roots:
        assert root not in node.evidence_roots

    assert (
        node.payload["synthetic_roots_are_observed_evidence"]
        is False
    )


def test_response_inherits_only_lawful_source_roots():
    graph, source, request = setup()

    response, node, _ = dispatch_challenge(
        graph=graph,
        request=request,
        queen_receipt=Queen(),
        source_nodes=(source,),
        created_at_ms=3001,
    )

    assert set(response.evidence_roots) == set(
        source.evidence_roots
    )

    assert set(node.evidence_roots) == set(
        source.evidence_roots
    )


def test_non_challenge_request_refused():
    graph, source, _ = setup()

    request = build_request(
        graph=graph,
        recurrence_index=0,
        request_kind="COMPARE",
        target="comparison",
        reason="test",
        source_receipt_id="queen-1",
    )

    with pytest.raises(
        ValueError,
        match="challenge_dispatch_requires_challenge_request",
    ):
        dispatch_challenge(
            graph=graph,
            request=request,
            queen_receipt=Queen(),
            source_nodes=(source,),
            created_at_ms=3001,
        )


def test_challenge_requires_source_nodes():
    graph, _, request = setup()

    with pytest.raises(
        ValueError,
        match="challenge_dispatch_source_nodes_required",
    ):
        dispatch_challenge(
            graph=graph,
            request=request,
            queen_receipt=Queen(),
            source_nodes=(),
            created_at_ms=3001,
        )
