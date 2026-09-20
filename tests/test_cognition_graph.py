import pytest

from strategies.relative_value_lab.cognition import (
    SCHEMA,
    add_cognition,
    add_hypothesis_forecasts,
    build_cognition,
    forecast_to_cognition,
)
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)
from strategies.volatility_breakout.models import Forecast


def root(ch: str) -> str:
    return "sha256:" + ch * 64


def frame():
    observation = ScoreObservation(
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
        observations=(observation,),
        assembled_at_ms=1000,
        freshness_window_ms=10000,
    )


def forecast(model_id: str, *, abstain: bool = False) -> Forecast:
    return Forecast(
        symbol="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=900,
        direction="ABSTAIN" if abstain else "UP",
        probability_positive_net=None if abstain else 0.61,
        expected_move_bps=None if abstain else 20.0,
        expected_cost_bps=8.0,
        expected_net_bps=None if abstain else 12.0,
        abstain=abstain,
        reason="test",
        model_id=model_id,
        hypothesis=f"hypothesis:{model_id}",
        raw_score=0.5,
        uncertainty=0.4,
        calibration_state="RESEARCH",
        feature_version="phase2.v1",
        reasons=(),
        inputs={"test": True},
        execution_eligible=False,
    )


def test_cognition_id_is_deterministic():
    a = build_cognition(
        role="PRIMARY_HYPOTHESIS",
        source_id="model-a",
        observed_at_ms=1000,
        available_at_ms=1001,
        evidence_roots=(root("a"),),
        lineage=("competition", "model-a"),
        transformation_version="forecast.model-a.v1",
        payload={"direction": "UP"},
    )

    b = build_cognition(
        role="PRIMARY_HYPOTHESIS",
        source_id="model-a",
        observed_at_ms=1000,
        available_at_ms=1001,
        evidence_roots=(root("a"),),
        lineage=("competition", "model-a"),
        transformation_version="forecast.model-a.v1",
        payload={"direction": "UP"},
    )

    assert a.cognition_id == b.cognition_id
    assert a.schema == SCHEMA


def test_forecast_cognition_preserves_roots_and_has_no_authority():
    f = forecast("breakout_continuation_v1")

    cognition = forecast_to_cognition(
        f,
        role="PRIMARY_HYPOTHESIS",
        evidence_roots=(root("b"), root("c")),
        available_at_ms=1001,
    )

    assert cognition.role == "PRIMARY_HYPOTHESIS"
    assert cognition.evidence_roots == tuple(
        sorted((root("b"), root("c")))
    )
    assert cognition.payload["model_id"] == "breakout_continuation_v1"
    assert cognition.challenger is True
    assert cognition.proposal_only is True
    assert cognition.execution_eligible is False
    assert cognition.promotion_eligible is False


def test_forecast_with_execution_authority_is_refused():
    f = Forecast(
        symbol="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=900,
        model_id="bad-model",
        execution_eligible=True,
    )

    with pytest.raises(
        ValueError,
        match="forecast_execution_authority_forbidden",
    ):
        forecast_to_cognition(
            f,
            role="PRIMARY_HYPOTHESIS",
            evidence_roots=(root("a"),),
        )


def test_primary_and_federated_forecasts_enter_same_world_graph():
    graph = WorldGraph(frame())

    primary = (
        forecast("breakout_continuation_v1"),
        forecast("exhaustion_mean_reversion_v1", abstain=True),
    )

    federated = (
        forecast("candidate_freqai_transparent_linear_v1"),
        forecast("candidate_finrl_conservative_policy_proxy_v1"),
        forecast("candidate_cex_multi_horizon_oracle_v1"),
    )

    nodes = add_hypothesis_forecasts(
        graph,
        primary_forecasts=primary,
        federated_forecasts=federated,
        evidence_roots=(root("a"),),
        created_at_ms=1001,
    )

    assert len(nodes) == 5

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=(
            "PRIMARY_HYPOTHESIS",
            "FEDERATED_CANDIDATE",
        ),
    )

    assert "PRIMARY_HYPOTHESIS" in view.families
    assert "FEDERATED_CANDIDATE" in view.families
    assert view.missing_expected_families == ()

    for node in view.nodes:
        assert node.organ_id == "phoenix_cognition"
        assert node.payload["schema"] == SCHEMA
        assert node.payload["execution_eligible"] is False
        assert node.payload["promotion_eligible"] is False


def test_cognition_roots_do_not_become_new_independent_observations():
    graph = WorldGraph(frame())

    f1 = forecast("breakout_continuation_v1")
    f2 = forecast("candidate_freqai_transparent_linear_v1")

    nodes = add_hypothesis_forecasts(
        graph,
        primary_forecasts=(f1,),
        federated_forecasts=(f2,),
        evidence_roots=(root("a"),),
        created_at_ms=1001,
    )

    assert nodes[0].evidence_roots == (root("a"),)
    assert nodes[1].evidence_roots == (root("a"),)

    view = graph.queen_view(created_at_ms=1002)

    assert view.independent_evidence_root_count == 1


def test_memory_role_can_be_non_proposal_context():
    cognition = build_cognition(
        role="MEMORY_CONTEXT",
        source_id="worker-memory",
        observed_at_ms=1000,
        available_at_ms=1000,
        evidence_roots=(root("a"),),
        lineage=("worker-memory",),
        transformation_version="worker-memory.v1",
        payload={"samples": 10},
        challenger=False,
        proposal_only=False,
        memory_only=True,
        historical_only=True,
    )

    assert cognition.memory_only is True
    assert cognition.proposal_only is False
    assert cognition.execution_eligible is False


def test_specialized_market_context_forecasts_get_dedicated_roles():
    from strategies.relative_value_lab.cognition import (
        add_specialized_market_context_forecasts,
    )

    graph = WorldGraph(frame())

    medium = forecast("medium_horizon_trend_v1")
    derivatives = forecast("derivatives_trend_v1")
    cex = forecast("candidate_cex_multi_horizon_oracle_v1")

    nodes = add_specialized_market_context_forecasts(
        graph,
        medium_horizon_forecasts=(medium,),
        derivatives_trend_forecasts=(derivatives,),
        cex_oracle_forecasts=(cex,),
        evidence_roots=(root("a"),),
        created_at_ms=1001,
    )

    assert {node.family for node in nodes} == {
        "MEDIUM_HORIZON_TREND",
        "DERIVATIVES_TREND",
        "CEX_MULTI_HORIZON_ORACLE",
    }

    for node in nodes:
        assert node.organ_id == "phoenix_cognition"
        assert node.evidence_roots == (root("a"),)
        assert node.payload["schema"] == SCHEMA
        assert node.payload["proposal_only"] is True
        assert node.payload["execution_eligible"] is False
        assert node.payload["promotion_eligible"] is False


def test_specialized_context_does_not_multiply_shared_market_evidence():
    from strategies.relative_value_lab.cognition import (
        add_specialized_market_context_forecasts,
    )

    graph = WorldGraph(frame())

    add_specialized_market_context_forecasts(
        graph,
        medium_horizon_forecasts=(
            forecast("medium_horizon_trend_v1"),
        ),
        derivatives_trend_forecasts=(
            forecast("derivatives_trend_v1"),
        ),
        cex_oracle_forecasts=(
            forecast("candidate_cex_multi_horizon_oracle_v1"),
        ),
        evidence_roots=(root("a"),),
        created_at_ms=1001,
    )

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=(
            "MEDIUM_HORIZON_TREND",
            "DERIVATIVES_TREND",
            "CEX_MULTI_HORIZON_ORACLE",
        ),
    )

    assert view.missing_expected_families == ()
    assert view.independent_evidence_root_count == 1


def test_derivatives_context_remains_research_only_even_when_directional():
    from strategies.relative_value_lab.cognition import (
        forecast_to_cognition,
    )

    f = Forecast(
        symbol="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=86400,
        direction="UP",
        probability_positive_net=0.64,
        expected_move_bps=60.0,
        expected_cost_bps=25.0,
        expected_net_bps=35.0,
        abstain=False,
        reason="accepted_historical_slice",
        model_id="derivatives_trend_v1",
        hypothesis="derivatives_medium_horizon_trend",
        raw_score=0.7,
        uncertainty=0.3,
        calibration_state="HISTORICAL_RESEARCH",
        feature_version="derivatives.v1",
        inputs={
            "price_data_source":
                "kraken_futures_live_perpetual_feed",
        },
        execution_eligible=False,
    )

    cognition = forecast_to_cognition(
        f,
        role="DERIVATIVES_TREND",
        evidence_roots=(root("a"),),
    )

    assert cognition.payload["direction"] == "UP"
    assert cognition.proposal_only is True
    assert cognition.execution_eligible is False
    assert cognition.promotion_eligible is False


def test_cex_oracle_is_context_not_independent_observation():
    from strategies.relative_value_lab.cognition import (
        forecast_to_cognition,
    )

    f = forecast("candidate_cex_multi_horizon_oracle_v1")

    cognition = forecast_to_cognition(
        f,
        role="CEX_MULTI_HORIZON_ORACLE",
        evidence_roots=(root("a"),),
    )

    assert cognition.role == "CEX_MULTI_HORIZON_ORACLE"
    assert cognition.evidence_roots == (root("a"),)
    assert cognition.challenger is True
    assert cognition.proposal_only is True


def _regime_rows(base_ts: int, *, upward: bool = True):
    rows = []
    price = 100.0

    for i in range(60):
        ts = base_ts - (59 - i) * 60_000

        if upward:
            close = 100.0 + i * 0.25
        else:
            close = 115.0 - i * 0.25

        open_ = price
        high = max(open_, close) + 0.1
        low = min(open_, close) - 0.1
        volume = 1000.0 + i * 10.0

        rows.append([
            ts,
            open_,
            high,
            low,
            close,
            volume,
        ])

        price = close

    return rows


def test_regime_oracle_bound_frames_are_timestamp_safe():
    from agents.oracle_regime import RegimeOracle

    oracle = RegimeOracle(
        "BTC/USD",
        min_duration_sec=0,
        confirm_bars=1,
    )

    observed = 1_700_000_000_000

    snapshot = oracle.evaluate_bound_frames(
        {
            "1m": _regime_rows(observed),
        },
        observed_at_ms=observed,
        spread_bps=5.0,
    )

    assert snapshot["timestamp"] == observed
    assert snapshot["source_mode"] == "BOUND_FRAMES"
    assert snapshot["symbol"] == "BTC/USD"
    assert snapshot["regime"]


def test_regime_oracle_refuses_future_frame_rows():
    from agents.oracle_regime import RegimeOracle

    oracle = RegimeOracle("BTC/USD")

    observed = 1_700_000_000_000

    rows = _regime_rows(observed)
    rows.append([
        observed + 1,
        100,
        101,
        99,
        100,
        1000,
    ])

    with pytest.raises(
        ValueError,
        match="regime_bound_frame_future_row_forbidden",
    ):
        oracle.evaluate_bound_frames(
            {"1m": rows},
            observed_at_ms=observed,
        )


def test_regime_oracle_replay_is_deterministic_for_same_inputs():
    from agents.oracle_regime import RegimeOracle

    observed = 1_700_000_000_000
    frames = {"1m": _regime_rows(observed)}

    a = RegimeOracle(
        "BTC/USD",
        min_duration_sec=0,
        confirm_bars=1,
    )

    b = RegimeOracle(
        "BTC/USD",
        min_duration_sec=0,
        confirm_bars=1,
    )

    sa = a.evaluate_bound_frames(
        frames,
        observed_at_ms=observed,
        spread_bps=4.0,
    )

    sb = b.evaluate_bound_frames(
        frames,
        observed_at_ms=observed,
        spread_bps=4.0,
    )

    assert sa == sb


def test_regime_oracle_enters_queen_as_context_not_evidence():
    from agents.oracle_regime import RegimeOracle
    from strategies.relative_value_lab.cognition import (
        add_regime_oracle_context,
    )

    graph = WorldGraph(frame())

    observed = 1000

    rows = []
    for i in range(60):
        ts = observed - (59 - i) * 10
        close = 100.0 + i * 0.05
        rows.append([
            ts,
            close - 0.02,
            close + 0.05,
            close - 0.05,
            close,
            1000 + i,
        ])

    oracle = RegimeOracle(
        "BTC/USD",
        min_duration_sec=0,
        confirm_bars=1,
    )

    node = add_regime_oracle_context(
        graph,
        oracle=oracle,
        frames={"1m": rows},
        observed_at_ms=observed,
        evidence_roots=(root("a"),),
        spread_bps=5.0,
        available_at_ms=1001,
    )

    assert node.family == "REGIME_CONTEXT"
    assert node.organ_id == "phoenix_cognition"
    assert node.evidence_roots == (root("a"),)

    payload = node.payload

    assert payload["schema"] == SCHEMA
    assert payload["role"] == "REGIME_CONTEXT"
    assert payload["proposal_only"] is False
    assert payload["challenger"] is True
    assert payload["execution_eligible"] is False
    assert payload["promotion_eligible"] is False

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=("REGIME_CONTEXT",),
    )

    assert view.missing_expected_families == ()
    assert view.independent_evidence_root_count == 1


def test_regime_context_does_not_replace_phase5_regime_evidence():
    from agents.oracle_regime import RegimeOracle
    from strategies.relative_value_lab.cognition import (
        add_regime_oracle_context,
    )
    from strategies.relative_value_lab.bee_evidence import (
        build_bee_evidence,
    )
    from strategies.relative_value_lab.world_graph_adapters import (
        add_bee_evidence,
    )

    graph = WorldGraph(frame())

    evidence = build_bee_evidence(
        family="REGIME",
        source_kind="DERIVED_PUBLIC_MARKET_STATE",
        source_ids=("regime-evidence",),
        evidence_roots=(root("a"),),
        lineage=("feature-regime",),
        transformation_version="regime.feature.v1",
        observed_at_ms=1000,
        available_at_ms=1000,
        freshness=1.0,
        confidence=0.8,
        payload={"regime_hint": "trend_expansion"},
    )

    add_bee_evidence(
        graph,
        evidence=evidence,
        created_at_ms=1000,
    )

    rows = []
    for i in range(60):
        ts = 1000 - (59 - i) * 10
        close = 100 + i * 0.05
        rows.append([
            ts,
            close,
            close + 0.1,
            close - 0.1,
            close,
            1000 + i,
        ])

    oracle = RegimeOracle(
        "BTC/USD",
        min_duration_sec=0,
        confirm_bars=1,
    )

    add_regime_oracle_context(
        graph,
        oracle=oracle,
        frames={"1m": rows},
        observed_at_ms=1000,
        evidence_roots=(root("a"),),
    )

    view = graph.queen_view(
        created_at_ms=1001,
        expected_families=(
            "REGIME",
            "REGIME_CONTEXT",
        ),
    )

    assert "REGIME" in view.families
    assert "REGIME_CONTEXT" in view.families
    assert view.independent_evidence_root_count == 1


def _feature_with_memory():
    from strategies.volatility_breakout.models import FeatureVector

    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=1000,
        price=100.0,
        realized_volatility_fast=0.01,
        realized_volatility_baseline=0.008,
        volatility_expansion=1.25,
        volume_zscore=0.5,
        trade_count_zscore=None,
        order_flow_imbalance=None,
        book_imbalance=0.1,
        spread_bps=5.0,
        depth_usd_25bps=10000.0,
        quote_volume_24h=1000000.0,
        return_5=0.01,
        freshness_sec=1.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        values={
            "phase2_regime_suppression": {
                "trend_expansion": {
                    "candidate_bad_model_v1": {
                        "suppressed": True,
                        "samples": 12,
                        "mean_net_bps": -8.2,
                    }
                }
            },
            "phase2_worker_signal_memory": {
                "exact": {
                    "worker_signal_rsi_v1|900|UP": {
                        "samples": 8,
                        "mean_net_bps": -6.0,
                        "directional_hit_rate": 0.35,
                    }
                },
                "model": {},
            },
        },
        complete=True,
    )


def test_phase2_memory_context_binds_both_existing_memories():
    from strategies.relative_value_lab.cognition import (
        add_phase2_memory_context,
    )

    graph = WorldGraph(frame())
    feature = _feature_with_memory()

    nodes = add_phase2_memory_context(
        graph,
        feature=feature,
        evidence_roots=(root("a"),),
        available_at_ms=1001,
    )

    assert len(nodes) == 2

    assert {node.family for node in nodes} == {
        "MEMORY_CONTEXT",
    }

    source_ids = {
        node.payload["source_id"]
        for node in nodes
    }

    assert source_ids == {
        "regime_suppression_memory",
        "worker_signal_memory",
    }

    for node in nodes:
        assert node.organ_id == "phoenix_cognition"
        assert node.payload["schema"] == SCHEMA
        assert node.payload["memory_only"] is True
        assert node.payload["proposal_only"] is False
        assert node.payload["challenger"] is False
        assert node.payload["execution_eligible"] is False
        assert node.payload["promotion_eligible"] is False


def test_regime_suppression_memory_preserves_existing_shape():
    from strategies.relative_value_lab.cognition import (
        feature_memory_to_cognition,
    )

    feature = _feature_with_memory()

    cognition = feature_memory_to_cognition(
        feature=feature,
        memory_key="phase2_regime_suppression",
        source_id="regime_suppression_memory",
        evidence_roots=(root("a"),),
    )

    assert cognition is not None

    memory = cognition.payload["memory"]

    assert (
        memory["trend_expansion"]
        ["candidate_bad_model_v1"]
        ["suppressed"]
        is True
    )

    assert (
        memory["trend_expansion"]
        ["candidate_bad_model_v1"]
        ["mean_net_bps"]
        == -8.2
    )


def test_worker_signal_memory_preserves_exact_and_model_buckets():
    from strategies.relative_value_lab.cognition import (
        feature_memory_to_cognition,
    )

    feature = _feature_with_memory()

    cognition = feature_memory_to_cognition(
        feature=feature,
        memory_key="phase2_worker_signal_memory",
        source_id="worker_signal_memory",
        evidence_roots=(root("a"),),
    )

    assert cognition is not None

    memory = cognition.payload["memory"]

    assert "exact" in memory
    assert "model" in memory

    row = memory["exact"]["worker_signal_rsi_v1|900|UP"]

    assert row["samples"] == 8
    assert row["mean_net_bps"] == -6.0
    assert row["directional_hit_rate"] == 0.35


def test_missing_memory_does_not_invent_memory_node():
    from dataclasses import replace
    from strategies.relative_value_lab.cognition import (
        feature_memory_to_cognition,
    )

    feature = replace(
        _feature_with_memory(),
        values={},
    )

    cognition = feature_memory_to_cognition(
        feature=feature,
        memory_key="phase2_worker_signal_memory",
        source_id="worker_signal_memory",
        evidence_roots=(root("a"),),
    )

    assert cognition is None


def test_memory_context_does_not_multiply_market_evidence():
    from strategies.relative_value_lab.cognition import (
        add_phase2_memory_context,
    )

    graph = WorldGraph(frame())

    add_phase2_memory_context(
        graph,
        feature=_feature_with_memory(),
        evidence_roots=(root("a"),),
        available_at_ms=1001,
    )

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=("MEMORY_CONTEXT",),
    )

    assert view.missing_expected_families == ()
    assert view.independent_evidence_root_count == 1


def test_memory_cannot_escalate_to_execution_authority():
    from strategies.relative_value_lab.cognition import CognitionNode

    with pytest.raises(
        ValueError,
        match="cognition_authority_escalation_forbidden",
    ):
        CognitionNode(
            schema=SCHEMA,
            cognition_id="cog_test",
            role="MEMORY_CONTEXT",
            source_id="bad-memory",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("memory",),
            transformation_version="memory.v1",
            payload={"samples": 10},
            challenger=False,
            proposal_only=False,
            memory_only=True,
            historical_only=True,
            execution_eligible=True,
            promotion_eligible=False,
        )


def _feature_with_frontier():
    from strategies.volatility_breakout.models import FeatureVector

    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=1000,
        price=100.0,
        realized_volatility_fast=0.01,
        realized_volatility_baseline=0.008,
        volatility_expansion=1.25,
        volume_zscore=0.5,
        trade_count_zscore=None,
        order_flow_imbalance=None,
        book_imbalance=0.1,
        spread_bps=5.0,
        depth_usd_25bps=10000.0,
        quote_volume_24h=1000000.0,
        return_5=0.01,
        freshness_sec=1.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        values={
            "regime_inputs": {
                "regime_hint": "trend_expansion",
                "confidence": 0.8,
            },
            "phase2_profitability_frontier": {
                "breakout": {
                    "eligible": True,
                    "mean_realized_net_bps": 7.5,
                    "settled_trades": 12,
                    "model_id": "breakout_continuation_v1",
                    "promotion_hint": "research_candidate",
                },
                "reversion": {
                    "eligible": False,
                    "regime_hint": "trend_expansion",
                },
            },
        },
        complete=True,
    )


def test_profitability_frontier_enters_world_graph_as_historical_context():
    from strategies.relative_value_lab.cognition import (
        add_profitability_frontier_context,
    )

    graph = WorldGraph(frame())

    node = add_profitability_frontier_context(
        graph,
        feature=_feature_with_frontier(),
        evidence_roots=(root("a"),),
        available_at_ms=1001,
    )

    assert node is not None
    assert node.family == "PROFITABILITY_FRONTIER"
    assert node.organ_id == "phoenix_cognition"
    assert node.evidence_roots == (root("a"),)

    payload = node.payload

    assert payload["schema"] == SCHEMA
    assert payload["role"] == "PROFITABILITY_FRONTIER"
    assert payload["historical_only"] is True
    assert payload["memory_only"] is True
    assert payload["proposal_only"] is False
    assert payload["execution_eligible"] is False
    assert payload["promotion_eligible"] is False


def test_profitability_frontier_preserves_settlement_truth():
    from strategies.relative_value_lab.cognition import (
        profitability_frontier_to_cognition,
    )

    cognition = profitability_frontier_to_cognition(
        feature=_feature_with_frontier(),
        evidence_roots=(root("a"),),
    )

    assert cognition is not None

    breakout = cognition.payload["frontier"]["breakout"]

    assert breakout["eligible"] is True
    assert breakout["mean_realized_net_bps"] == 7.5
    assert breakout["settled_trades"] == 12
    assert breakout["model_id"] == "breakout_continuation_v1"


def test_profitability_frontier_does_not_convert_promotion_hint_to_authority():
    from strategies.relative_value_lab.cognition import (
        profitability_frontier_to_cognition,
    )

    cognition = profitability_frontier_to_cognition(
        feature=_feature_with_frontier(),
        evidence_roots=(root("a"),),
    )

    assert cognition is not None

    breakout = cognition.payload["frontier"]["breakout"]

    assert breakout["promotion_hint"] == "research_candidate"
    assert cognition.promotion_eligible is False
    assert cognition.execution_eligible is False


def test_missing_profitability_frontier_does_not_invent_context():
    from dataclasses import replace
    from strategies.relative_value_lab.cognition import (
        profitability_frontier_to_cognition,
    )

    feature = replace(
        _feature_with_frontier(),
        values={},
    )

    cognition = profitability_frontier_to_cognition(
        feature=feature,
        evidence_roots=(root("a"),),
    )

    assert cognition is None


def test_profitability_frontier_does_not_multiply_market_roots():
    from strategies.relative_value_lab.cognition import (
        add_profitability_frontier_context,
    )

    graph = WorldGraph(frame())

    add_profitability_frontier_context(
        graph,
        feature=_feature_with_frontier(),
        evidence_roots=(root("a"),),
        available_at_ms=1001,
    )

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=("PROFITABILITY_FRONTIER",),
    )

    assert view.missing_expected_families == ()
    assert view.independent_evidence_root_count == 1


def test_positive_thesis_crystal_binds_as_memory_only():
    from strategies.relative_value_lab.cognition import (
        crystal_row_to_cognition,
    )

    crystal = {
        "crystal_id": "crystal-positive-1",
        "crystal_family": "thesis_capability",
        "symbol": "BTC/USD",
        "regime_hint": "trend_expansion",
        "evidence_strength": 0.8,
        "hypothesis": "breakout_continuation",
    }

    cognition = crystal_row_to_cognition(
        crystal=crystal,
        role="POSITIVE_THESIS_CRYSTAL",
        observed_at_ms=1000,
        evidence_roots=(root("a"),),
    )

    assert cognition.role == "POSITIVE_THESIS_CRYSTAL"
    assert cognition.memory_only is True
    assert cognition.proposal_only is False
    assert cognition.challenger is False
    assert cognition.execution_eligible is False
    assert cognition.promotion_eligible is False
    assert cognition.payload["crystal"]["evidence_strength"] == 0.8


def test_negative_capability_crystal_binds_as_warning_memory():
    from strategies.relative_value_lab.cognition import (
        crystal_row_to_cognition,
    )

    crystal = {
        "crystal_id": "crystal-negative-1",
        "crystal_family": "negative_capability",
        "symbol_class": "long_tail",
        "regime_hint": "trend_expansion",
        "evidence_strength": 0.9,
        "reason": "historically_failed_after_costs",
    }

    cognition = crystal_row_to_cognition(
        crystal=crystal,
        role="NEGATIVE_CAPABILITY_CRYSTAL",
        observed_at_ms=1000,
        evidence_roots=(root("a"),),
    )

    assert cognition.role == "NEGATIVE_CAPABILITY_CRYSTAL"
    assert cognition.memory_only is True
    assert cognition.payload["crystal"]["evidence_strength"] == 0.9
    assert cognition.execution_eligible is False
    assert cognition.promotion_eligible is False


def test_crystal_family_role_mismatch_is_refused():
    from strategies.relative_value_lab.cognition import (
        crystal_row_to_cognition,
    )

    with pytest.raises(
        ValueError,
        match="crystal_family_role_mismatch",
    ):
        crystal_row_to_cognition(
            crystal={
                "crystal_id": "bad",
                "crystal_family": "negative_capability",
            },
            role="POSITIVE_THESIS_CRYSTAL",
            observed_at_ms=1000,
            evidence_roots=(root("a"),),
        )


def test_positive_and_negative_crystals_enter_same_queen_view():
    from strategies.relative_value_lab.cognition import (
        add_crystal_context,
    )

    graph = WorldGraph(frame())

    thesis = (
        {
            "crystal_id": "thesis-1",
            "crystal_family": "thesis_capability",
            "symbol": "BTC/USD",
            "regime_hint": "trend_expansion",
            "evidence_strength": 0.7,
        },
    )

    negative = (
        {
            "crystal_id": "negative-1",
            "crystal_family": "negative_capability",
            "symbol_class": "major",
            "regime_hint": "trend_expansion",
            "evidence_strength": 0.6,
        },
    )

    nodes = add_crystal_context(
        graph,
        thesis_crystals=thesis,
        negative_crystals=negative,
        observed_at_ms=1000,
        evidence_roots=(root("a"),),
        available_at_ms=1001,
    )

    assert len(nodes) == 2

    view = graph.queen_view(
        created_at_ms=1002,
        expected_families=(
            "POSITIVE_THESIS_CRYSTAL",
            "NEGATIVE_CAPABILITY_CRYSTAL",
        ),
    )

    assert view.missing_expected_families == ()
    assert view.independent_evidence_root_count == 1


def test_crystal_memory_summary_preserves_support_and_warning():
    from dataclasses import replace
    from strategies.relative_value_lab.cognition import (
        crystal_memory_summary_to_cognition,
    )

    feature = replace(
        _feature_with_memory(),
        values={
            "phase2_crystal_memory": {
                "positive_recent": 2,
                "negative_recent": 1,
                "support_score": 1.4,
                "warning_score": 0.7,
                "regime_hint": "trend_expansion",
                "symbol_class": "major",
                "symbol": "BTC/USD",
            }
        },
    )

    cognition = crystal_memory_summary_to_cognition(
        feature=feature,
        evidence_roots=(root("a"),),
    )

    assert cognition is not None
    assert cognition.role == "MEMORY_CONTEXT"
    assert cognition.memory_only is True

    memory = cognition.payload["memory"]

    assert memory["positive_recent"] == 2
    assert memory["negative_recent"] == 1
    assert memory["support_score"] == 1.4
    assert memory["warning_score"] == 0.7


def test_crystals_do_not_become_independent_market_witnesses():
    from strategies.relative_value_lab.cognition import (
        add_crystal_context,
    )

    graph = WorldGraph(frame())

    add_crystal_context(
        graph,
        thesis_crystals=(
            {
                "crystal_id": "t1",
                "crystal_family": "thesis_capability",
                "evidence_strength": 0.5,
            },
            {
                "crystal_id": "t2",
                "crystal_family": "thesis_capability",
                "evidence_strength": 0.4,
            },
        ),
        negative_crystals=(
            {
                "crystal_id": "n1",
                "crystal_family": "negative_capability",
                "evidence_strength": 0.6,
            },
        ),
        observed_at_ms=1000,
        evidence_roots=(root("a"),),
    )

    view = graph.queen_view(created_at_ms=1001)

    assert view.independent_evidence_root_count == 1


def test_candidate_influence_trace_contains_only_actual_influences():
    from strategies.relative_value_lab.cognition import (
        add_cognition,
        bind_candidate_influences,
        build_cognition,
        candidate_influence_trace,
    )

    graph = WorldGraph(frame())

    regime = add_cognition(
        graph,
        cognition=build_cognition(
            role="REGIME_CONTEXT",
            source_id="regime-oracle",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("regime",),
            transformation_version="regime.v1",
            payload={"regime": "TREND_UP"},
            proposal_only=False,
        ),
    )

    memory = add_cognition(
        graph,
        cognition=build_cognition(
            role="MEMORY_CONTEXT",
            source_id="worker-memory",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("memory",),
            transformation_version="memory.v1",
            payload={"samples": 8},
            challenger=False,
            proposal_only=False,
            memory_only=True,
            historical_only=True,
        ),
    )

    unrelated = add_cognition(
        graph,
        cognition=build_cognition(
            role="NEGATIVE_CAPABILITY_CRYSTAL",
            source_id="unused-crystal",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("crystal",),
            transformation_version="crystal.v1",
            payload={"warning": 1.0},
            challenger=False,
            proposal_only=False,
            memory_only=True,
            historical_only=True,
        ),
    )

    conclusion = add_cognition(
        graph,
        cognition=forecast_to_cognition(
            forecast("breakout_continuation_v1"),
            role="PRIMARY_HYPOTHESIS",
            evidence_roots=(root("a"),),
            available_at_ms=1001,
        ),
    )

    created = bind_candidate_influences(
        graph,
        conclusion_node=conclusion,
        influences=(
            (regime, "regime_gate_used"),
            (memory, "worker_memory_used"),
        ),
    )

    recovered = candidate_influence_trace(
        graph,
        conclusion_node_id=conclusion.node_id,
    )

    assert created == recovered

    assert regime.node_id in recovered.influence_node_ids
    assert memory.node_id in recovered.influence_node_ids

    assert unrelated.node_id not in recovered.influence_node_ids

    assert set(recovered.influence_families) == {
        "REGIME_CONTEXT",
        "MEMORY_CONTEXT",
    }


def test_influence_edges_are_visible_to_queen():
    from strategies.relative_value_lab.cognition import (
        add_cognition,
        bind_candidate_influences,
        build_cognition,
    )

    graph = WorldGraph(frame())

    context = add_cognition(
        graph,
        cognition=build_cognition(
            role="PROFITABILITY_FRONTIER",
            source_id="frontier",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("frontier",),
            transformation_version="frontier.v1",
            payload={"eligible": True},
            challenger=False,
            proposal_only=False,
            memory_only=True,
            historical_only=True,
        ),
    )

    conclusion = add_cognition(
        graph,
        cognition=forecast_to_cognition(
            forecast("breakout_continuation_v1"),
            role="PRIMARY_HYPOTHESIS",
            evidence_roots=(root("a"),),
            available_at_ms=1001,
        ),
    )

    bind_candidate_influences(
        graph,
        conclusion_node=conclusion,
        influences=(
            (context, "adaptive_recovery_frontier_gate"),
        ),
    )

    view = graph.queen_view(created_at_ms=1002)

    influence_edges = [
        edge
        for edge in view.edges
        if edge.edge_type == "INFLUENCES"
    ]

    assert len(influence_edges) == 1
    assert influence_edges[0].source_node_id == context.node_id
    assert influence_edges[0].target_node_id == conclusion.node_id
    assert (
        influence_edges[0].metadata["reason"]
        == "adaptive_recovery_frontier_gate"
    )


def test_duplicate_influence_is_collapsed():
    from strategies.relative_value_lab.cognition import (
        add_cognition,
        bind_candidate_influences,
        build_cognition,
    )

    graph = WorldGraph(frame())

    context = add_cognition(
        graph,
        cognition=build_cognition(
            role="REGIME_CONTEXT",
            source_id="regime",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("regime",),
            transformation_version="regime.v1",
            payload={"regime": "TREND_UP"},
            proposal_only=False,
        ),
    )

    conclusion = add_cognition(
        graph,
        cognition=forecast_to_cognition(
            forecast("breakout_continuation_v1"),
            role="PRIMARY_HYPOTHESIS",
            evidence_roots=(root("a"),),
        ),
    )

    trace = bind_candidate_influences(
        graph,
        conclusion_node=conclusion,
        influences=(
            (context, "regime_gate"),
            (context, "regime_gate"),
        ),
    )

    assert len(trace.influence_node_ids) == 1
    assert len(trace.influence_edge_ids) == 1


def test_influence_requires_explicit_reason():
    from strategies.relative_value_lab.cognition import (
        add_cognition,
        bind_candidate_influences,
        build_cognition,
    )

    graph = WorldGraph(frame())

    context = add_cognition(
        graph,
        cognition=build_cognition(
            role="REGIME_CONTEXT",
            source_id="regime",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("regime",),
            transformation_version="regime.v1",
            payload={"regime": "TREND_UP"},
            proposal_only=False,
        ),
    )

    conclusion = add_cognition(
        graph,
        cognition=forecast_to_cognition(
            forecast("breakout_continuation_v1"),
            role="PRIMARY_HYPOTHESIS",
            evidence_roots=(root("a"),),
        ),
    )

    with pytest.raises(
        ValueError,
        match="influence_reason_required",
    ):
        bind_candidate_influences(
            graph,
            conclusion_node=conclusion,
            influences=((context, ""),),
        )


def test_influence_trace_has_no_authority_effect():
    from strategies.relative_value_lab.cognition import (
        add_cognition,
        bind_candidate_influences,
        build_cognition,
    )

    graph = WorldGraph(frame())

    context = add_cognition(
        graph,
        cognition=build_cognition(
            role="POSITIVE_THESIS_CRYSTAL",
            source_id="crystal",
            observed_at_ms=1000,
            available_at_ms=1000,
            evidence_roots=(root("a"),),
            lineage=("crystal",),
            transformation_version="crystal.v1",
            payload={"support": 0.8},
            challenger=False,
            proposal_only=False,
            memory_only=True,
            historical_only=True,
        ),
    )

    conclusion = add_cognition(
        graph,
        cognition=forecast_to_cognition(
            forecast("breakout_continuation_v1"),
            role="PRIMARY_HYPOTHESIS",
            evidence_roots=(root("a"),),
        ),
    )

    trace = bind_candidate_influences(
        graph,
        conclusion_node=conclusion,
        influences=((context, "crystal_support_used"),),
    )

    assert trace.execution_eligible is False
    assert trace.promotion_eligible is False

    edge = next(iter(graph._edges.values()))

    assert edge.metadata["authority_effect"] == "NONE"
