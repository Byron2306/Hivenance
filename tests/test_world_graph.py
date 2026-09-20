from strategies.relative_value_lab.bee_evidence import build_bee_evidence
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_graph_adapters import add_bee_evidence
from strategies.relative_value_lab.world_score import CanonicalWorldScore, ScoreObservation


def _frame():
    obs = ScoreObservation(
        observation_id="obs-1",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1_000,
        received_at_ms=1_001,
        evidence_root="sha256:" + "a" * 64,
        payload={"price": 100.0},
    )
    return CanonicalWorldScore.assemble(
        observations=[obs],
        assembled_at_ms=1_002,
        freshness_window_ms=15_000,
    )


def test_world_graph_preserves_world_binding_and_queen_view():
    frame = _frame()
    graph = WorldGraph(frame)
    flow_evidence = build_bee_evidence(
        family="FLOW",
        source_kind="PUBLIC_TRADE_OR_BOOK_DELTA_FLOW",
        source_ids=("flow-test-1",),
        evidence_roots=("sha256:" + "b" * 64,),
        lineage=("flow-v1",),
        transformation_version="flow-imbalance-v1",
        observed_at_ms=1_000,
        available_at_ms=1_003,
        freshness=0.9,
        confidence=0.8,
        payload={"state": "FLOW_MIXED"},
    )
    flow = add_bee_evidence(
        graph,
        evidence=flow_evidence,
        created_at_ms=1_003,
    )
    horizon = graph.add_node(
        organ_id="horizon",
        family="HORIZON",
        created_at_ms=1_003,
        evidence_roots=["sha256:" + "c" * 64],
        lineage_id="horizon-v1",
        transformation_id="horizon-context-v1",
        payload={"alignment": "CONFLICT"},
        freshness=0.8,
        uncertainty=0.3,
    )
    graph.add_edge(
        edge_type="CONTRADICTS",
        source_node_id=flow.node_id,
        target_node_id=horizon.node_id,
    )
    view = graph.queen_view(
        created_at_ms=1_004,
        expected_families=("FLOW", "HORIZON", "LIQUIDITY"),
    )
    assert view.world_state_id == frame.world_state_id
    assert view.world_state_hash == frame.world_state_hash
    assert view.node_count == 2
    assert len(view.contradiction_edges) == 1
    assert view.missing_expected_families == ("LIQUIDITY",)
    assert view.execution_eligible is False
    assert view.promotion_eligible is False


def test_synthetic_node_is_visible_but_not_counted_as_observed_independence():
    frame = _frame()
    graph = WorldGraph(frame)
    graph.add_node(
        organ_id="mystique",
        family="COUNTERFACTUAL",
        created_at_ms=1_003,
        evidence_roots=["sha256:" + "d" * 64],
        lineage_id="mystique-v1",
        transformation_id="synthetic-variation-v1",
        payload={"variation": "shuffle"},
        synthetic=True,
    )
    view = graph.queen_view(created_at_ms=1_004)
    assert len(view.synthetic_node_ids) == 1
    assert view.independent_evidence_root_count == 0
