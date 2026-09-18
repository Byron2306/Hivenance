from __future__ import annotations

import math

from strategies.relative_value_lab.dataset import RelativeValueDatasetBuilder
from strategies.relative_value_lab.pair_lab import PairRelationshipLab


def synthetic_rows(samples: int = 100, interval_sec: int = 5):
    rows = []
    spread = 0.01
    for i in range(samples):
        ts = 1_000_000 + i * interval_sec * 1000
        b = 100.0 * math.exp(0.0002 * i + 0.001 * math.sin(i / 11.0))
        spread = 0.86 * spread + 0.0007 * math.sin(i / 4.0)
        a = math.exp(0.15 + 1.02 * math.log(b) + spread)
        for symbol, mid, sign in (("A/USD", a, 1.0), ("B/USD", b, -1.0)):
            rows.append({
                "symbol": symbol,
                "timestamp_ms": ts,
                "mid": mid,
                "spread_bps": 2.0 + 0.1 * (i % 3),
                "book_imbalance_25bps": sign * 0.1 * math.sin(i / 6.0),
                "quote_ofi_proxy": sign * 0.15 * math.sin(i / 5.0),
                "aggressor_flow_imbalance": sign * 0.2 * math.cos(i / 7.0),
                "trade_count": 5 + i % 4,
                "trade_intensity_per_sec": 1.0 + (i % 4) / interval_sec,
                "depth_recovery_score": 0.02 * math.sin(i / 3.0),
                "data_quality": 1.0,
            })
    return rows


def builder():
    lab = PairRelationshipLab(
        min_samples=30,
        min_return_correlation=0.0,
        max_half_life_fraction=1.0,
        max_structural_break_score=50.0,
        min_stability_score=0.0,
    )
    return RelativeValueDatasetBuilder(
        relationship_window_samples=50,
        minimum_relationship_samples=30,
        horizons_seconds=(10, 30),
        future_tolerance_fraction=0.7,
        lab=lab,
    )


def test_dataset_freezes_features_before_future_labels():
    rows = synthetic_rows()
    examples, summary = builder().build(rows, venue="test")
    assert examples
    assert summary.examples == len(examples)

    target = examples[len(examples) // 3]
    cutoff = target.timestamp_ms

    mutated = []
    for row in rows:
        changed = dict(row)
        if row["timestamp_ms"] > cutoff:
            if row["symbol"] == "A/USD":
                changed["mid"] = float(row["mid"]) * 1.05
            else:
                changed["mid"] = float(row["mid"]) * 0.97
        mutated.append(changed)

    altered, _ = builder().build(mutated, venue="test")
    altered_by_id = {
        (example.pair_id, example.timestamp_ms): example
        for example in altered
    }
    counterpart = altered_by_id[(target.pair_id, target.timestamp_ms)]

    # Feature evidence at t must be unchanged by mutations after t.
    assert counterpart.feature_digest == target.feature_digest
    assert counterpart.hedge_alpha == target.hedge_alpha
    assert counterpart.hedge_ratio == target.hedge_ratio
    assert counterpart.spread == target.spread

    # At least one future label should respond to the deliberately mutated future.
    assert counterpart.labels_bps != target.labels_bps


def test_dataset_labels_are_strictly_future_and_horizon_bounded():
    examples, _ = builder().build(synthetic_rows(), venue="test")
    checked = 0
    for example in examples:
        for horizon in (10, 30):
            key = f"{horizon}s"
            label_ts = example.label_timestamps_ms.get(key)
            if label_ts is None:
                continue
            assert label_ts >= example.timestamp_ms + horizon * 1000
            # 5-second cadence and 70% tolerance means at most 3.5s late.
            assert label_ts <= example.timestamp_ms + horizon * 1000 + 3500
            checked += 1
    assert checked > 0


def test_dataset_objects_are_research_only():
    examples, summary = builder().build(synthetic_rows(), venue="test")
    assert examples
    assert summary.authority.endswith("no_execution_or_promotion_authority")
    assert all(example.execution_eligible is False for example in examples)
