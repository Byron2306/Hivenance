from __future__ import annotations

from strategies.relative_value_lab.dataset import RelativeValueExample
from strategies.relative_value_lab.evaluation import (
    ExpandingRidgeModel,
    RelativeValueWalkForwardEvaluator,
)


def example(index: int, *, horizon: int = 10, label_delay_ms: int = 10_000) -> RelativeValueExample:
    ts = 1_000_000 + index * 5_000
    label = float((index % 7) - 3)
    return RelativeValueExample(
        schema="hivenance_relative_value_example_v1",
        example_id=f"e{index}",
        pair_id="A/USD__B/USD",
        symbol_a="A/USD",
        symbol_b="B/USD",
        timestamp_ms=ts,
        sample_interval_sec=5.0,
        relationship_samples=60,
        hedge_alpha=0.1,
        hedge_ratio=1.0,
        relationship_stability=0.8,
        half_life_seconds=30.0,
        mean_reversion_speed_per_sec=0.02,
        ou_equilibrium=0.0,
        spread_std=0.01,
        structural_break_state="STABLE",
        spread=0.001 * ((index % 5) - 2),
        spread_zscore=float((index % 5) - 2),
        relative_return_1step_bps=float((index % 3) - 1),
        relative_return_3step_bps=float((index % 5) - 2),
        relative_return_6step_bps=float((index % 7) - 3),
        pair_spread_cost_bps_proxy=2.0,
        quote_ofi_delta=0.1 * ((index % 3) - 1),
        aggressor_flow_delta=0.2 * ((index % 5) - 2),
        book_imbalance_delta=0.1,
        depth_recovery_delta=0.01,
        trade_intensity_sum=2.0,
        data_quality_min=1.0,
        labels_bps={f"{horizon}s": label},
        label_timestamps_ms={f"{horizon}s": ts + label_delay_ms},
        feature_digest=f"d{index}",
    )


def test_ridge_training_admits_only_labels_known_by_cutoff():
    rows = [example(i) for i in range(40)]
    model = ExpandingRidgeModel(ridge_alpha=4.0, minimum_train_samples=17)

    cutoff = rows[25].timestamp_ms
    fit = model.fit(rows, horizon_seconds=10, cutoff_timestamp_ms=cutoff)
    assert fit is not None

    expected = sum(
        1 for row in rows
        if int(row.label_timestamps_ms["10s"]) <= cutoff
    )
    assert fit.samples == expected
    assert fit.samples < 26


def test_walk_forward_contains_boring_baselines_and_research_only_outputs():
    rows = [example(i) for i in range(60)]
    evaluator = RelativeValueWalkForwardEvaluator(
        horizons_seconds=(10,),
        minimum_train_samples=17,
        ridge_alpha=4.0,
    )
    predictions, metrics = evaluator.evaluate(rows)

    model_ids = {row.model_id for row in predictions}
    assert "baseline_zero_v1" in model_ids
    assert "baseline_continuation_v1" in model_ids
    assert "baseline_reversal_v1" in model_ids
    assert "relative_value_ou_mean_reversion_v1" in model_ids
    assert "relative_value_expanding_ridge_v1" in model_ids
    assert all(row.execution_eligible is False for row in predictions)
    assert metrics


def test_walk_forward_ridge_never_trains_on_current_unsettled_label():
    rows = [example(i, label_delay_ms=60_000) for i in range(80)]
    evaluator = RelativeValueWalkForwardEvaluator(
        horizons_seconds=(10,),
        minimum_train_samples=17,
        ridge_alpha=4.0,
    )
    predictions, _ = evaluator.evaluate(rows)
    ridge = [row for row in predictions if row.model_id == "relative_value_expanding_ridge_v1"]
    assert ridge
    for row in ridge:
        current_index = int(row.example_id[1:])
        current_ts = rows[current_index].timestamp_ms
        known = sum(
            1 for historic in rows[:current_index]
            if int(historic.label_timestamps_ms["10s"]) <= current_ts
        )
        assert row.train_samples == known
