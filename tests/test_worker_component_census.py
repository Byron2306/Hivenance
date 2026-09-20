from strategies.relative_value_lab.worker_component_census import classify_worker_component


def test_worker_component_requires_independent_world_depth_before_harmful():
    row=classify_worker_component(
        mask_id="NO_WORKER_RSI",
        model_id="worker_signal_rsi_v1",
        testable_worlds=203,
        changed_worlds=4,
        decision_changes=4,
        helpful_changes=0,
        harmful_changes=4,
        mean_delta_bps=-129.5,
        dependence_adjusted_worlds=3,
        positive_cohorts=0,
        negative_cohorts=3,
    )
    assert row.classification=="INFLUENTIAL_UNDERPOWERED"


def test_worker_component_mixed_when_both_cohort_signs_at_depth():
    row=classify_worker_component(
        mask_id="NO_WORKER_RSI2",
        model_id="worker_signal_rsi2_v1",
        testable_worlds=203,
        changed_worlds=7,
        decision_changes=7,
        helpful_changes=1,
        harmful_changes=6,
        mean_delta_bps=-105.2,
        dependence_adjusted_worlds=5,
        positive_cohorts=1,
        negative_cohorts=4,
    )
    assert row.classification=="HISTORICALLY_MIXED"


def test_worker_component_inert_stays_inert():
    row=classify_worker_component(
        mask_id="NO_WORKER_SMA",
        model_id="worker_signal_sma_v1",
        testable_worlds=203,
        changed_worlds=0,
        decision_changes=0,
        helpful_changes=0,
        harmful_changes=0,
        mean_delta_bps=None,
        dependence_adjusted_worlds=0,
        positive_cohorts=0,
        negative_cohorts=0,
    )
    assert row.classification=="INERT_ON_TESTED_WORLDS"
