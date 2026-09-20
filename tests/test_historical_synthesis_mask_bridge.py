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
