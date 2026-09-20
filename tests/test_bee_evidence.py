import pytest

from strategies.relative_value_lab.bee_evidence import (
    SCHEMA,
    build_bee_evidence,
)


def root(c):
    return "sha256:" + c * 64


def test_bee_evidence_deterministic():
    kwargs = dict(
        family="LIQUIDITY",
        source_kind="PUBLIC_ORDER_BOOK",
        source_ids=("run-1",),
        evidence_roots=(root("a"),),
        lineage=("feature_engine.v1", "liquidity.v1"),
        transformation_version="liquidity.spread_depth.v1",
        observed_at_ms=1000,
        available_at_ms=1001,
        freshness=1.0,
        confidence=0.9,
        payload={"spread_bps": 2.0},
    )

    a = build_bee_evidence(**kwargs)
    b = build_bee_evidence(**kwargs)

    assert a.schema == SCHEMA
    assert a.evidence_id == b.evidence_id
    assert a.execution_eligible is False
    assert a.promotion_eligible is False


def test_present_evidence_requires_root():
    with pytest.raises(ValueError, match="present_without_evidence_root"):
        build_bee_evidence(
            family="FLOW",
            source_kind="PUBLIC_TRADE_FLOW",
            source_ids=("run-1",),
            evidence_roots=(),
            lineage=("flow.v1",),
            transformation_version="flow.v1",
            observed_at_ms=1000,
            available_at_ms=1000,
            freshness=1.0,
            confidence=0.5,
            payload={},
        )


def test_explicit_missing_evidence_can_abstain():
    e = build_bee_evidence(
        family="FLOW",
        source_kind="PUBLIC_TRADE_FLOW",
        source_ids=(),
        evidence_roots=(),
        lineage=("flow.v1",),
        transformation_version="flow.v1",
        observed_at_ms=1000,
        available_at_ms=1000,
        freshness=0.0,
        confidence=0.0,
        missingness=("sequential_trade_tape_unavailable",),
        abstention=True,
        payload={},
    )

    assert e.abstention is True
    assert e.missingness == ("sequential_trade_tape_unavailable",)


def test_time_reversal_refused():
    with pytest.raises(ValueError, match="available_before_observation"):
        build_bee_evidence(
            family="VOLATILITY",
            source_kind="PUBLIC_MARKET_SERIES",
            source_ids=("run-1",),
            evidence_roots=(root("b"),),
            lineage=("vol.v1",),
            transformation_version="vol.v1",
            observed_at_ms=2000,
            available_at_ms=1999,
            freshness=1.0,
            confidence=1.0,
            payload={},
        )

from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_graph_adapters import add_bee_evidence
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


def _frame():
    obs = ScoreObservation(
        observation_id="obs-1",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1001,
        evidence_root=root("c"),
        payload={"price": 100.0},
    )
    return CanonicalWorldScore.assemble(
        observations=[obs],
        assembled_at_ms=1002,
    )


def test_bee_evidence_enters_world_graph_without_root_mutation():
    e = build_bee_evidence(
        family="LIQUIDITY",
        source_kind="PUBLIC_ORDER_BOOK",
        source_ids=("run-1:BTC/USD",),
        evidence_roots=(root("d"),),
        lineage=("feature_engine.v1", "liquidity.v1"),
        transformation_version="liquidity.spread_depth.v1",
        observed_at_ms=1000,
        available_at_ms=1001,
        freshness=0.9,
        confidence=0.8,
        payload={"spread_bps": 3.0},
    )

    graph = WorldGraph(_frame())
    node = add_bee_evidence(graph, evidence=e)

    assert node.family == "LIQUIDITY"
    assert node.evidence_roots == (root("d"),)
    assert node.freshness == 0.9
    assert node.uncertainty == pytest.approx(0.2)

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=("LIQUIDITY", "FLOW"),
    )

    assert "LIQUIDITY" in view.families
    assert view.missing_expected_families == ("FLOW",)


class FeatureStub:
    def __init__(self):
        self.symbol = "BTC/USD"
        self.timestamp_ms = 10_000
        self.spread_bps = 2.5
        self.depth_usd_25bps = 250000.0
        self.book_imbalance = 0.2
        self.realized_volatility_fast = 0.01
        self.realized_volatility_baseline = 0.008
        self.volatility_expansion = 1.25
        self.freshness_sec = 5.0
        self.data_quality = 0.95
        self.values = {
            "book_imbalance_is_proxy": True,
        }


def test_liquidity_feature_becomes_canonical_bee():
    from strategies.relative_value_lab.bee_evidence import liquidity_from_feature

    f = FeatureStub()
    e = liquidity_from_feature(f, evidence_root=root("e"))

    assert e.family == "LIQUIDITY"
    assert e.evidence_roots == (root("e"),)
    assert e.payload["spread_bps"] == 2.5
    assert e.payload["depth_usd_25bps"] == 250000.0
    assert e.payload["book_imbalance_is_proxy"] is True
    assert e.abstention is False


def test_volatility_feature_becomes_canonical_bee():
    from strategies.relative_value_lab.bee_evidence import volatility_from_feature

    f = FeatureStub()
    e = volatility_from_feature(f, evidence_root=root("f"))

    assert e.family == "VOLATILITY"
    assert e.evidence_roots == (root("f"),)
    assert e.payload["realized_volatility_fast"] == 0.01
    assert e.payload["volatility_expansion"] == 1.25
    assert e.abstention is False


def test_missing_liquidity_is_explicit_abstention():
    from strategies.relative_value_lab.bee_evidence import liquidity_from_feature

    f = FeatureStub()
    f.spread_bps = None
    f.depth_usd_25bps = None
    f.book_imbalance = None

    e = liquidity_from_feature(f, evidence_root=root("e"))

    assert e.abstention is True
    assert e.evidence_roots == ()
    assert "spread_bps_unavailable" in e.missingness


def test_missing_volatility_is_explicit_abstention():
    from strategies.relative_value_lab.bee_evidence import volatility_from_feature

    f = FeatureStub()
    f.realized_volatility_fast = None
    f.realized_volatility_baseline = None
    f.volatility_expansion = None

    e = volatility_from_feature(f, evidence_root=root("f"))

    assert e.abstention is True
    assert e.evidence_roots == ()
    assert "volatility_expansion_unavailable" in e.missingness


def test_flow_abstains_when_only_book_proxy_exists():
    from strategies.relative_value_lab.bee_evidence import flow_from_feature

    f = FeatureStub()
    f.order_flow_imbalance = None
    f.values = {
        "book_imbalance_is_proxy": True,
        "order_flow_imbalance_status":
            "UNAVAILABLE_REQUIRES_SEQUENTIAL_TRADE_OR_BOOK_DELTAS",
    }

    e = flow_from_feature(f, evidence_root=root("g"))

    assert e.family == "FLOW"
    assert e.abstention is True
    assert e.evidence_roots == ()
    assert e.payload["book_imbalance_proxy"] == 0.2
    assert e.payload["book_imbalance_is_proxy"] is True
    assert "true_order_flow_unavailable" in e.missingness


def test_flow_present_when_true_order_flow_exists():
    from strategies.relative_value_lab.bee_evidence import flow_from_feature

    f = FeatureStub()
    f.order_flow_imbalance = 0.35
    f.values = {
        "book_imbalance_is_proxy": True,
        "order_flow_imbalance_status": "PRESENT",
    }

    e = flow_from_feature(f, evidence_root=root("h"))

    assert e.family == "FLOW"
    assert e.abstention is False
    assert e.evidence_roots == (root("h"),)
    assert e.payload["order_flow_imbalance"] == 0.35


def test_cross_market_canonicalizes_real_cross_section():
    from strategies.relative_value_lab.bee_evidence import (
        cross_market_from_comparison,
    )
    from strategies.relative_value_lab.comparison_engine import (
        ComparisonEngine,
        ComparisonReference,
    )

    peers = [
        ComparisonReference(
            reference_id="eth-1",
            observed_at_ms=9_990,
            symbol="ETH/USD",
            utc_hour=0,
            features={"return_5": 10.0},
            evidence_roots=(root("i"),),
        ),
        ComparisonReference(
            reference_id="sol-1",
            observed_at_ms=9_995,
            symbol="SOL/USD",
            utc_hour=0,
            features={"return_5": -5.0},
            evidence_roots=(root("j"),),
        ),
    ]

    result = ComparisonEngine().cross_section(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        current_features={"return_5": 15.0},
        peers=peers,
        feature_names=("return_5",),
        tolerance_ms=60_000,
    )

    e = cross_market_from_comparison(result)

    assert e.family == "CROSS_MARKET"
    assert e.abstention is False
    assert e.evidence_roots == tuple(sorted((root("i"), root("j"))))
    assert e.payload["matched_n"] == 2
    assert e.payload["metrics"]["return_5"]["peer_median"] == pytest.approx(2.5)


def test_cross_market_empty_peer_set_abstains_without_fake_root():
    from strategies.relative_value_lab.bee_evidence import (
        cross_market_from_comparison,
    )
    from strategies.relative_value_lab.comparison_engine import ComparisonEngine

    result = ComparisonEngine().cross_section(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        current_features={"return_5": 15.0},
        peers=[],
        feature_names=("return_5",),
    )

    e = cross_market_from_comparison(result)

    assert e.abstention is True
    assert e.evidence_roots == ()
    assert "cross_market_peer_set_unavailable" in e.missingness


def test_cross_market_rejects_non_cross_section_comparison():
    from strategies.relative_value_lab.bee_evidence import (
        cross_market_from_comparison,
    )
    from strategies.relative_value_lab.comparison_engine import (
        ComparisonEngine,
        ComparisonReference,
    )

    ref = ComparisonReference(
        reference_id="old-btc",
        observed_at_ms=5_000,
        symbol="BTC/USD",
        utc_hour=0,
        features={"return_5": 1.0},
        evidence_roots=(root("k"),),
    )

    result = ComparisonEngine().same_utc_hour_baseline(
        observed_at_ms=10_000,
        symbol="BTC/USD",
        utc_hour=0,
        current_features={"return_5": 2.0},
        references=(ref,),
        feature_names=("return_5",),
    )

    with pytest.raises(
        ValueError,
        match="cross_market_requires_cross_section_result",
    ):
        cross_market_from_comparison(result)


def test_path_geometry_canonicalizes_backward_path():
    from strategies.relative_value_lab.bee_evidence import (
        path_geometry_from_worker_series,
    )

    ws = {
        "closes": [
            100, 101, 102, 101, 103, 104, 105, 104, 106,
            107, 108, 107, 109, 110, 111, 112, 113,
        ]
    }

    e = path_geometry_from_worker_series(
        symbol="BTC/USD",
        timestamp_ms=10_000,
        worker_series=ws,
        evidence_root=root("l"),
    )

    assert e.family == "PATH_GEOMETRY"
    assert e.abstention is False
    assert e.evidence_roots == (root("l"),)
    assert 0.0 <= e.payload["path_efficiency"] <= 1.0
    assert 0.0 <= e.payload["flip_rate"] <= 1.0
    assert 0.0 <= e.payload["range_position"] <= 1.0
    assert e.payload["range_bps"] > 0


def test_path_geometry_insufficient_history_abstains():
    from strategies.relative_value_lab.bee_evidence import (
        path_geometry_from_worker_series,
    )

    e = path_geometry_from_worker_series(
        symbol="BTC/USD",
        timestamp_ms=10_000,
        worker_series={"closes": [100, 101, 102]},
        evidence_root=root("m"),
    )

    assert e.abstention is True
    assert e.evidence_roots == ()
    assert "insufficient_path_history" in e.missingness


def test_path_geometry_uses_only_supplied_pre_t_closes():
    from strategies.relative_value_lab.bee_evidence import (
        path_geometry_from_worker_series,
    )

    base = {
        "closes": list(range(100, 117)),
    }

    e1 = path_geometry_from_worker_series(
        symbol="BTC/USD",
        timestamp_ms=10_000,
        worker_series=base,
        evidence_root=root("n"),
    )

    # Future prices are deliberately not supplied to the function.
    e2 = path_geometry_from_worker_series(
        symbol="BTC/USD",
        timestamp_ms=10_000,
        worker_series={"closes": list(range(100, 117))},
        evidence_root=root("n"),
    )

    assert e1.payload == e2.payload
    assert e1.evidence_id == e2.evidence_id


def test_regime_feature_becomes_timestamp_safe_canonical_evidence():
    from strategies.relative_value_lab.bee_evidence import regime_from_feature

    f = FeatureStub()
    f.values = {
        "regime_inputs": {
            "regime_hint": "trend_expansion",
            "trend_direction": "up",
            "liquidity_state": "normal",
            "participation_state": "expanding",
            "confidence": 0.82,
        }
    }

    e = regime_from_feature(
        f,
        component_evidence_roots=(root("o"), root("p")),
    )

    assert e.family == "REGIME"
    assert e.abstention is False
    assert e.observed_at_ms == f.timestamp_ms
    assert e.available_at_ms == f.timestamp_ms
    assert e.payload["regime_hint"] == "trend_expansion"
    assert e.confidence == pytest.approx(0.82)
    assert e.evidence_roots == tuple(sorted((root("o"), root("p"))))


def test_regime_preserves_component_roots_instead_of_minting_new_independence():
    from strategies.relative_value_lab.bee_evidence import regime_from_feature

    f = FeatureStub()
    f.values = {
        "regime_inputs": {
            "regime_hint": "balanced_transition",
            "trend_direction": "flat",
            "liquidity_state": "normal",
            "participation_state": "normal",
            "confidence": 0.55,
        }
    }

    components = (root("q"), root("r"), root("q"))

    e = regime_from_feature(
        f,
        component_evidence_roots=components,
    )

    assert e.evidence_roots == tuple(sorted(set(components)))
    assert e.payload["component_evidence_roots"] == tuple(
        sorted(set(components))
    )


def test_regime_without_component_roots_abstains():
    from strategies.relative_value_lab.bee_evidence import regime_from_feature

    f = FeatureStub()
    f.values = {
        "regime_inputs": {
            "regime_hint": "quiet_range",
            "trend_direction": "flat",
            "liquidity_state": "normal",
            "participation_state": "soft",
            "confidence": 0.7,
        }
    }

    e = regime_from_feature(
        f,
        component_evidence_roots=(),
    )

    assert e.abstention is True
    assert e.evidence_roots == ()
    assert "regime_component_roots_unavailable" in e.missingness


def test_regime_without_classification_abstains():
    from strategies.relative_value_lab.bee_evidence import regime_from_feature

    f = FeatureStub()
    f.values = {}

    e = regime_from_feature(
        f,
        component_evidence_roots=(root("s"),),
    )

    assert e.abstention is True
    assert "regime_hint_unavailable" in e.missingness


def test_public_derivatives_snapshot_becomes_canonical_carry_evidence():
    from strategies.relative_value_lab.bee_evidence import (
        derivatives_carry_from_snapshot,
    )

    snapshot = {
        "funding_rate": 0.0001,
        "funding_rate_source": "kraken_futures_live",
        "mark_price": 100.5,
        "index_price": 100.0,
        "spread_bps": 2.0,
        "data_quality": 1.0,
    }

    e = derivatives_carry_from_snapshot(
        symbol="BTC/USD",
        snapshot=snapshot,
        observed_at_ms=10_000,
        available_at_ms=10_010,
        evidence_root=root("t"),
    )

    assert e.family == "DERIVATIVES_CARRY"
    assert e.abstention is False
    assert e.evidence_roots == (root("t"),)
    assert e.payload["funding_rate"] == pytest.approx(0.0001)
    assert e.payload["basis_bps"] == pytest.approx(50.0)
    assert e.available_at_ms >= e.observed_at_ms


def test_manual_funding_input_does_not_become_market_evidence():
    from strategies.relative_value_lab.bee_evidence import (
        derivatives_carry_from_snapshot,
    )

    snapshot = {
        "funding_rate": 0.0002,
        "funding_rate_source": "manual_input_no_live_feed",
        "mark_price": None,
        "index_price": None,
        "data_quality": 1.0,
    }

    e = derivatives_carry_from_snapshot(
        symbol="BTC/USD",
        snapshot=snapshot,
        observed_at_ms=10_000,
        available_at_ms=10_000,
        evidence_root=root("u"),
    )

    assert e.abstention is True
    assert e.evidence_roots == ()
    assert "manual_funding_input_not_market_evidence" in e.missingness


def test_information_arrival_is_explicit_abstention_without_market_event_feed():
    from strategies.relative_value_lab.bee_evidence import (
        information_arrival_abstention,
    )

    e = information_arrival_abstention(
        symbol="BTC/USD",
        observed_at_ms=10_000,
    )

    assert e.family == "INFORMATION_ARRIVAL"
    assert e.abstention is True
    assert e.evidence_roots == ()
    assert (
        "timestamp_proven_external_information_feed_unavailable"
        in e.missingness
    )


def test_slow_capital_onchain_is_explicit_abstention_without_provenance():
    from strategies.relative_value_lab.bee_evidence import (
        slow_capital_onchain_abstention,
    )

    e = slow_capital_onchain_abstention(
        symbol="BTC/USD",
        observed_at_ms=10_000,
    )

    assert e.family == "SLOW_CAPITAL_ONCHAIN"
    assert e.abstention is True
    assert e.evidence_roots == ()
    assert (
        "explicit_slow_latency_timestamp_provenance_unavailable"
        in e.missingness
    )


def test_queen_accepts_all_phase5_families_only_as_bee_evidence():
    from strategies.relative_value_lab.world_graph_adapters import add_bee_evidence

    graph = WorldGraph(_frame())

    present_families = (
        "TEMPORAL_PARTICIPATION",
        "LIQUIDITY",
        "VOLATILITY",
        "CROSS_MARKET",
        "PATH_GEOMETRY",
        "REGIME",
        "DERIVATIVES_CARRY",
    )

    for i, family in enumerate(present_families):
        e = build_bee_evidence(
            family=family,
            source_kind="TEST_PUBLIC_SOURCE",
            source_ids=(f"source-{i}",),
            evidence_roots=(root(chr(ord("a") + (i % 20))),),
            lineage=("phase5.test.v1", family.lower()),
            transformation_version=f"{family.lower()}.v1",
            observed_at_ms=1000,
            available_at_ms=1001,
            freshness=1.0,
            confidence=0.8,
            payload={"family_under_test": family},
        )
        add_bee_evidence(graph, evidence=e)

    # Conditional / unavailable families still enter canonically as explicit
    # abstentions rather than disappearing or fabricating roots.
    for family in (
        "FLOW",
        "INFORMATION_ARRIVAL",
        "SLOW_CAPITAL_ONCHAIN",
    ):
        e = build_bee_evidence(
            family=family,
            source_kind="TEST_UNAVAILABLE_SOURCE",
            source_ids=(),
            evidence_roots=(),
            lineage=("phase5.test.v1", family.lower()),
            transformation_version=f"{family.lower()}.unavailable.v1",
            observed_at_ms=1000,
            available_at_ms=1000,
            freshness=0.0,
            confidence=0.0,
            missingness=("test_source_unavailable",),
            abstention=True,
            payload={
                "family_under_test": family,
                "status": "UNAVAILABLE",
            },
        )
        add_bee_evidence(graph, evidence=e)

    expected = (
        "TEMPORAL_PARTICIPATION",
        "FLOW",
        "LIQUIDITY",
        "VOLATILITY",
        "CROSS_MARKET",
        "PATH_GEOMETRY",
        "REGIME",
        "DERIVATIVES_CARRY",
        "INFORMATION_ARRIVAL",
        "SLOW_CAPITAL_ONCHAIN",
    )

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=expected,
    )

    assert set(expected).issubset(set(view.families))
    assert view.missing_expected_families == ()

    major_nodes = [
        node for node in view.nodes
        if node.family in expected
    ]

    assert len(major_nodes) == len(expected)

    for node in major_nodes:
        assert node.organ_id == "bee_evidence"
        assert node.payload["schema"] == "hivenance_bee_evidence_v1"
        assert node.payload["family"] == node.family
        assert node.execution_eligible is False
        assert node.promotion_eligible is False


def test_queen_refuses_private_shape_for_phase5_major_family():
    graph = WorldGraph(_frame())

    graph.add_node(
        organ_id="legacy_private_flow_adapter",
        family="FLOW",
        created_at_ms=1001,
        evidence_roots=(root("z"),),
        lineage_id="legacy.flow.v1",
        transformation_id="legacy.flow.private.v1",
        payload={
            "schema": "legacy_private_flow_v1",
            "flow": 0.5,
        },
        freshness=1.0,
        uncertainty=0.2,
    )

    with pytest.raises(
        ValueError,
        match="queen_noncanonical_phase5_evidence",
    ):
        graph.queen_view(created_at_ms=1002)
