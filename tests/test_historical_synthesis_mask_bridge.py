import pytest

from strategies.relative_value_lab.edge_ecology import (
    EdgeEcology,
)
from strategies.relative_value_lab.historical_mask_engine import (
    historical_mask_plan,
)
from strategies.relative_value_lab.historical_synthesis_mask_bridge import (
    run_masked_synthesis,
)
from strategies.relative_value_lab.synthesis_runtime import (
    SynthesisRuntime,
)
from strategies.relative_value_lab.statistical_synthesis import (
    StatisticalEvidence,
    StatisticsBee,
    SynthesisBee,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


def frame():
    obs = ScoreObservation(
        observation_id="o",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=10,
        received_at_ms=10,
        evidence_root=(
            "sha256:" + "a" * 64
        ),
        payload={"price": 100},
    )

    return CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=10,
        freshness_window_ms=100,
    )


def edge():
    ecology = EdgeEcology()

    return ecology.snapshot(
        timestamp_ms=10,
        pair_id="BTC/USD",
        voices=(
            ecology.flow_voice(
                taker_buy_volume=60,
                taker_sell_volume=40,
            ),
            ecology.liquidity_voice(
                bid_depth=60,
                ask_depth=40,
                spread_bps=2,
            ),
            ecology.volatility_voice(
                returns=(
                    .01,
                    .02,
                    -.01,
                ),
                baseline_vol=.01,
            ),
        ),
    )


def inputs():
    return {
        "frame": frame(),
        "now_ms": 10,
        "edge_snapshot": edge(),
        "edge_roots": {
            "FLOW": (
                "sha256:" + "b" * 64,
            ),
            "LIQUIDITY": (
                "sha256:" + "c" * 64,
            ),
            "VOLATILITY": (
                "sha256:" + "d" * 64,
            ),
        },
    }


def families(run):
    return set(
        run.cycle.queen_view.families
    )


def test_full_hive_preserves_all_edge_families():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "FULL_HIVE"
        ),
        runtime_inputs=inputs(),
    )

    assert {
        "FLOW",
        "LIQUIDITY",
        "VOLATILITY",
    }.issubset(
        families(run)
    )


def test_no_flow_removes_only_flow():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_FLOW"
        ),
        runtime_inputs=inputs(),
    )

    fs = families(run)

    assert "FLOW" not in fs
    assert "LIQUIDITY" in fs
    assert "VOLATILITY" in fs


def test_no_liquidity_removes_only_liquidity():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_LIQUIDITY"
        ),
        runtime_inputs=inputs(),
    )

    fs = families(run)

    assert "LIQUIDITY" not in fs
    assert "FLOW" in fs
    assert "VOLATILITY" in fs


def test_no_volatility_removes_only_volatility():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_VOLATILITY"
        ),
        runtime_inputs=inputs(),
    )

    fs = families(run)

    assert "VOLATILITY" not in fs
    assert "FLOW" in fs
    assert "LIQUIDITY" in fs


def test_no_comparison_disables_comparison_runtime_organ():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_COMPARISON"
        ),
        runtime_inputs=inputs(),
    )

    receipt = next(
        x
        for x in run.cycle.organ_receipts
        if x.organ_id
        == "comparison_engine"
    )

    assert receipt.state == "DISABLED"


def test_no_learning_disables_learning_runtime_organ():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_LEARNING"
        ),
        runtime_inputs=inputs(),
    )

    receipt = next(
        x
        for x in run.cycle.organ_receipts
        if x.organ_id
        == "learning_memory"
    )

    assert receipt.state == "DISABLED"


def test_no_temporal_participation_disables_correct_runtime_organ():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_TEMPORAL_PARTICIPATION"
        ),
        runtime_inputs=inputs(),
    )

    receipt = next(
        x
        for x in run.cycle.organ_receipts
        if x.organ_id
        == "temporal_participation_bee"
    )

    assert receipt.state == "DISABLED"


def test_upper_spine_mask_refuses_until_runtime_integration_exists():
    with pytest.raises(
        ValueError,
        match="not_executable",
    ):
        run_masked_synthesis(
            runtime=SynthesisRuntime(),
            mask=historical_mask_plan(
                "NO_QUEEN"
            ),
            runtime_inputs=inputs(),
        )


def test_masked_replay_preserves_observed_world():
    base = inputs()

    full = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "FULL_HIVE"
        ),
        runtime_inputs=base,
    )

    masked = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_FLOW"
        ),
        runtime_inputs=base,
    )

    assert (
        full.cycle.world_state_id
        == masked.cycle.world_state_id
    )

    assert (
        full.cycle.world_state_hash
        == masked.cycle.world_state_hash
    )


def test_mask_bridge_never_grants_authority():
    run = run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan(
            "NO_FLOW"
        ),
        runtime_inputs=inputs(),
    )

    assert run.execution_eligible is False
    assert run.promotion_eligible is False
    assert (
        run.cycle.execution_eligible
        is False
    )



def test_no_statistics_disables_statistics_bee_without_changing_world():
    base=inputs()
    bee=StatisticsBee()
    bee.ingest(
        StatisticalEvidence(
            evidence_id="stat-1",
            scope="exact|m|BTC/USD|10|TREND",
            observed_at_ms=1,
            available_at_ms=5,
            realized_bps=4.0,
            positive=True,
            evidence_root="sha256:"+"e"*64,
        )
    )
    base["statistical_state"]=SynthesisBee().synthesize(
        exact=bee.snapshot(
            scope="exact|m|BTC/USD|10|TREND",
            as_of_ms=10,
        )
    )

    full=run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan("FULL_HIVE"),
        runtime_inputs=base,
    )
    masked=run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan("NO_STATISTICS"),
        runtime_inputs=base,
    )

    assert "STATISTICAL_SYNTHESIS" in families(full)
    assert "STATISTICAL_SYNTHESIS" not in families(masked)
    receipt=next(
        x for x in masked.cycle.organ_receipts
        if x.organ_id=="statistics_bee"
    )
    assert receipt.state=="DISABLED"
    assert full.cycle.world_state_hash==masked.cycle.world_state_hash



def test_probabilistic_masks_remove_only_their_runtime_organs():
    base=inputs()
    base["regime_context"]=__import__(
        "strategies.relative_value_lab.regime_context",
        fromlist=["build_regime_context"],
    ).build_regime_context(
        as_of_ms=10,
        deterministic={"regime_hint":"trend_expansion","confidence":.7},
        bayesian={
            "posterior_id":"p1",
            "probabilities":{"TREND":.7,"MEAN_REVERSION":.1,"TRANSITION":.15,"STRESS":.05},
            "dominant_regime":"TREND",
            "entropy":.4,
            "change_point_probability":.2,
            "evidence_available_at_ms":5,
        },
    )
    base["external_context"]={
        "schema":"hivenance_external_statistics_context_v1",
        "features":(
            {"evidence_root":"sha256:"+"e"*64,"metric":"ETF_NET_FLOW_USD"},
        ),
    }
    base["calibration_context"]={
        "schema":"hivenance_calibration_health_v1",
        "health_id":"h1",
        "overall_drift_score":.2,
    }
    base["ml_challengers"]=(
        {
            "schema":"hivenance_ml_challenger_context_v1",
            "receipt_id":"ml1",
            "evidence_root":"sha256:"+"f"*64,
            "uncertainty_pressure":.2,
        },
    )

    full=run_masked_synthesis(
        runtime=SynthesisRuntime(),
        mask=historical_mask_plan("FULL_HIVE"),
        runtime_inputs=base,
    )
    external_node=next(
        node for node in full.cycle.queen_view.nodes
        if node.family=="EXTERNAL_STATISTICS"
    )
    assert external_node.organ_id=="bee_evidence"
    assert external_node.payload["schema"]=="hivenance_bee_evidence_v1"
    expectations={
        "NO_BAYES":("regime_context","REGIME_CONTEXT"),
        "NO_EXTERNAL":("external_statistics","EXTERNAL_STATISTICS"),
        "NO_CONFORMAL":("calibration_context","CALIBRATION_CONTEXT"),
        "NO_ML":("ml_challenger","ML_CHALLENGER"),
    }
    for mask_id,(organ_id,family) in expectations.items():
        masked=run_masked_synthesis(
            runtime=SynthesisRuntime(),
            mask=historical_mask_plan(mask_id),
            runtime_inputs=base,
        )
        assert family in families(full)
        assert family not in families(masked)
        receipt=next(x for x in masked.cycle.organ_receipts if x.organ_id==organ_id)
        assert receipt.state=="DISABLED"
        assert masked.cycle.world_state_hash==full.cycle.world_state_hash
