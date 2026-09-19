from strategies.relative_value_lab.comparison_engine import (
    ComparisonEngine,
    ComparisonReference,
    add_comparison_result,
)
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore, ScoreObservation


def _root(c):
    return "sha256:" + c * 64


def _frame():
    return CanonicalWorldScore.assemble(
        observations=[
            ScoreObservation(
                observation_id="o",
                source_id="public",
                source_class="public_market",
                scope="BTC/USD",
                observed_at_ms=10_000,
                received_at_ms=10_001,
                evidence_root=_root("a"),
                payload={"price": 100},
            )
        ],
        assembled_at_ms=10_002,
    )


def _ref(i, ts, symbol, hour, value, *, selected=None, label=None):
    return ComparisonReference(
        reference_id=f"r{i}",
        observed_at_ms=ts,
        symbol=symbol,
        utc_hour=hour,
        features={"x": value},
        evidence_roots=(_root(chr(98 + i)),),
        selected=selected,
        event_label=label,
    )


def test_same_hour_comparison_is_strictly_prior_and_graph_bound():
    eng = ComparisonEngine()
    refs = [
        _ref(0, 1_000, "BTC/USD", 12, 10),
        _ref(1, 2_000, "BTC/USD", 12, 20),
        _ref(2, 20_000, "BTC/USD", 12, 999),  # future, forbidden
        _ref(3, 2_000, "BTC/USD", 13, 777),
    ]
    result = eng.same_utc_hour_baseline(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        utc_hour=12,
        current_features={"x": 30},
        references=refs,
        feature_names=("x",),
    )
    assert result.matched_n == 2
    assert result.metrics["x"]["reference_median"] == 15
    assert result.metrics["x"]["delta"] == 15

    graph = WorldGraph(_frame())
    node = add_comparison_result(graph, result=result, created_at_ms=10_003)
    assert node.world_state_id == graph.frame.world_state_id
    assert node.family == "COMPARISON"
    assert node.execution_eligible is False


def test_cross_section_never_uses_future_peer():
    eng = ComparisonEngine()
    peers = [
        _ref(0, 9_900, "ETH/USD", 12, 10),
        _ref(1, 10_001, "SOL/USD", 12, 1000),
        _ref(2, 9_950, "XRP/USD", 12, 20),
    ]
    result = eng.cross_section(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        current_features={"x": 30},
        peers=peers,
        feature_names=("x",),
        tolerance_ms=200,
    )
    assert result.matched_n == 2
    assert result.metrics["x"]["peer_median"] == 15


def test_selected_rejected_and_event_control_are_descriptive():
    eng = ComparisonEngine()
    refs = [
        _ref(0, 1_000, "BTC/USD", 1, 10, selected=True, label="EVENT"),
        _ref(1, 2_000, "ETH/USD", 1, 14, selected=True, label="EVENT"),
        _ref(2, 3_000, "SOL/USD", 1, 2, selected=False, label="CONTROL"),
        _ref(3, 4_000, "XRP/USD", 1, 4, selected=False, label="CONTROL"),
    ]
    sr = eng.selected_vs_rejected(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        references=refs,
        feature_names=("x",),
    )
    assert sr.metrics["x"]["selected_median"] == 12
    assert sr.metrics["x"]["rejected_median"] == 3
    ec = eng.event_vs_control(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        references=refs,
        event_label="EVENT",
        control_label="CONTROL",
        feature_names=("x",),
    )
    assert ec.metrics["x"]["delta"] == 9
    assert ec.execution_eligible is False


def test_nearest_prior_states_excludes_future():
    eng = ComparisonEngine()
    refs = [
        _ref(0, 1_000, "BTC/USD", 1, 9),
        _ref(1, 2_000, "BTC/USD", 1, 50),
        _ref(2, 20_000, "BTC/USD", 1, 10),
    ]
    result = eng.nearest_prior_states(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        current_features={"x": 10},
        references=refs,
        feature_names=("x",),
        k=1,
    )
    assert result.reference_ids == ("r0",)
