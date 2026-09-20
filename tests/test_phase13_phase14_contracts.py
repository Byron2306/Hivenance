from strategies.relative_value_lab.phase13_experiment import (
    PHASE13_REQUIRED_BOOKS,
    PHASE13_REQUIRED_HORIZONS_SECONDS,
    build_phase13_freeze,
)
from strategies.relative_value_lab.phase14_scientific_gate import (
    summarize_book,
    validate_phase14_input,
)


def test_phase13_freeze_separates_confirmatory_and_adaptive_books():
    freeze=build_phase13_freeze(
        organ_roster=["statistics_bee","learning_memory"],
        model_roster=["breakout_continuation_v1"],
        queen_epoch_rules={"version":1},
        recurrence_bound=3,
        comparison_rules={"version":1},
        cost_model={"venue":"kraken","version":1},
    )
    assert freeze.books==PHASE13_REQUIRED_BOOKS
    assert freeze.horizons_seconds==PHASE13_REQUIRED_HORIZONS_SECONDS
    assert freeze.frozen_book_can_change_modes is False
    assert freeze.adaptive_book_can_change_modes is True
    assert freeze.execution_eligible is False


def test_phase14_refuses_cross_freeze_analysis():
    try:
        validate_phase14_input(expected_freeze_id="p13f_a",receipt_freeze_ids=["p13f_b"])
    except ValueError as exc:
        assert "freeze_mismatch" in str(exc)
    else:
        raise AssertionError("expected freeze mismatch refusal")


def test_phase14_requires_depth_before_candidate():
    row=summarize_book(
        book_id="FULL_HIVE_FROZEN",
        realized_net_bps=[10.0,12.0,8.0],
        world_ids=["a","b","c"],
        minimum_samples=30,
        minimum_distinct_market_worlds=20,
    )
    assert row.classification=="INSUFFICIENT_EVIDENCE"
