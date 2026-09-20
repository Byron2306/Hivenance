import pytest

from strategies.relative_value_lab.historical_causal_prosecution import (
    ADVERSARIAL_ATTACKS,
    PAIRED_MASKS,
    HistoricalOrganProsecution,
    classify_historical_result,
    make_historical_prosecution_receipt,
)


def result(
    *,
    organ_id="FLOW",
    mask_id="NO_FLOW",
    available=True,
    invoked_count=10,
    non_default_output_count=8,
    paired_world_count=10,
    dependence_adjusted_world_count=7,
    decision_change_count=4,
    direction_change_count=2,
    abstention_change_count=2,
    selection_change_count=0,
    full_hive_mean_net_bps=5.0,
    ablated_mean_net_bps=2.0,
    historical_paired_delta_bps=3.0,
    uncertainty_bps=1.0,
    classification="HISTORICALLY_USEFUL",
):
    return HistoricalOrganProsecution(
        organ_id=organ_id,
        mask_id=mask_id,
        available=available,
        invoked_count=invoked_count,
        non_default_output_count=(
            non_default_output_count
        ),
        paired_world_count=paired_world_count,
        dependence_adjusted_world_count=(
            dependence_adjusted_world_count
        ),
        decision_change_count=(
            decision_change_count
        ),
        direction_change_count=(
            direction_change_count
        ),
        abstention_change_count=(
            abstention_change_count
        ),
        selection_change_count=(
            selection_change_count
        ),
        full_hive_mean_net_bps=(
            full_hive_mean_net_bps
        ),
        ablated_mean_net_bps=(
            ablated_mean_net_bps
        ),
        historical_paired_delta_bps=(
            historical_paired_delta_bps
        ),
        uncertainty_bps=uncertainty_bps,
        classification=classification,
    )


def test_master_plan_mask_roster_is_exact_and_complete():
    assert PAIRED_MASKS == (
        "FULL_HIVE",
        "NO_LONG_HORIZON_LATTICE",
        "NO_CEX_ORACLE",
        "NO_COMPARISON",
        "NO_COIN_SELECTOR",
        "NO_REGIME",
        "NO_FLOW",
        "NO_LIQUIDITY",
        "NO_VOLATILITY",
        "NO_CROSS_MARKET",
        "NO_TEMPORAL_PARTICIPATION",
        "NO_WORKERS",
        "NO_CRYSTALS",
        "NO_LEARNING",
        "NO_STATISTICS",
        "NO_BAYES",
        "NO_EXTERNAL",
        "NO_CONFORMAL",
        "NO_ML",
        "NO_VNS_PHRASE",
        "NO_TEMPORAL_TEXTURE",
        "NO_QUORUM",
        "NO_QUEEN",
        "NO_MYSTIQUE",
        "NO_METABOLISM",
        "NO_POLLEN",
        "SIMPLE_MOMENTUM",
        "SIMPLE_REVERSION",
        "DETERMINISTIC_RANDOM",
        "NO_TRADE",
    )


def test_master_plan_attack_roster_is_exact():
    assert ADVERSARIAL_ATTACKS == (
        "SHUFFLE_EVIDENCE",
        "DELAY_EVIDENCE",
        "DUPLICATE_LINEAGE",
        "FALSE_UNISON",
        "STALE_WORLD_BINDING",
        "MISSING_VOICE",
        "ROOT_SUBSTITUTION",
        "TIME_SHIFT_PLACEBO",
    )


def test_historical_utility_is_not_prospective_utility():
    receipt = make_historical_prosecution_receipt(
        organ_results=(
            result(),
        )
    )

    assert receipt.historical_only is True

    assert (
        receipt.prospective_usefulness_proven
        is False
    )

    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_historically_useful_organ_survives():
    receipt = make_historical_prosecution_receipt(
        organ_results=(
            result(
                organ_id="FLOW",
                mask_id="NO_FLOW",
            ),
        )
    )

    assert receipt.survivor_ids == (
        "FLOW",
    )


def test_historically_harmful_organ_does_not_survive():
    receipt = make_historical_prosecution_receipt(
        organ_results=(
            result(
                organ_id="FLOW",
                mask_id="NO_FLOW",
                historical_paired_delta_bps=-2.0,
                classification=(
                    "HISTORICALLY_HARMFUL"
                ),
            ),
        )
    )

    assert receipt.survivor_ids == ()


def test_influential_but_underpowered_organ_is_preserved_for_prospective_test():
    receipt = make_historical_prosecution_receipt(
        organ_results=(
            result(
                organ_id="QUEEN",
                mask_id="NO_QUEEN",
                historical_paired_delta_bps=None,
                classification="INFLUENTIAL",
            ),
        )
    )

    assert receipt.survivor_ids == (
        "QUEEN",
    )


def test_insufficient_evidence_is_not_silently_dropped():
    receipt = make_historical_prosecution_receipt(
        organ_results=(
            result(
                organ_id="MYSTIQUE",
                mask_id="NO_MYSTIQUE",
                historical_paired_delta_bps=None,
                classification=(
                    "INSUFFICIENT_EVIDENCE"
                ),
            ),
        )
    )

    assert receipt.survivor_ids == (
        "MYSTIQUE",
    )


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (
            dict(
                available=False,
                invoked_count=0,
                decision_change_count=0,
                historical_paired_delta_bps=None,
                minimum_paired_worlds_met=False,
            ),
            "UNAVAILABLE",
        ),
        (
            dict(
                available=True,
                invoked_count=0,
                decision_change_count=0,
                historical_paired_delta_bps=None,
                minimum_paired_worlds_met=False,
            ),
            "AVAILABLE",
        ),
        (
            dict(
                available=True,
                invoked_count=5,
                decision_change_count=0,
                historical_paired_delta_bps=None,
                minimum_paired_worlds_met=True,
            ),
            "INVOKED",
        ),
        (
            dict(
                available=True,
                invoked_count=5,
                decision_change_count=2,
                historical_paired_delta_bps=2.0,
                minimum_paired_worlds_met=False,
            ),
            "INSUFFICIENT_EVIDENCE",
        ),
        (
            dict(
                available=True,
                invoked_count=5,
                decision_change_count=2,
                historical_paired_delta_bps=None,
                minimum_paired_worlds_met=True,
            ),
            "INFLUENTIAL",
        ),
        (
            dict(
                available=True,
                invoked_count=5,
                decision_change_count=2,
                historical_paired_delta_bps=2.0,
                minimum_paired_worlds_met=True,
            ),
            "HISTORICALLY_USEFUL",
        ),
        (
            dict(
                available=True,
                invoked_count=5,
                decision_change_count=2,
                historical_paired_delta_bps=-2.0,
                minimum_paired_worlds_met=True,
            ),
            "HISTORICALLY_HARMFUL",
        ),
        (
            dict(
                available=True,
                invoked_count=5,
                decision_change_count=2,
                historical_paired_delta_bps=0.0,
                minimum_paired_worlds_met=True,
            ),
            "HISTORICALLY_NEUTRAL",
        ),
    ],
)
def test_mechanistic_classification_ladder(
    kwargs,
    expected,
):
    assert (
        classify_historical_result(
            **kwargs
        )
        == expected
    )


def test_result_exposes_every_master_plan_output_field():
    row = result()

    payload = row.to_dict()

    for key in (
        "available",
        "invoked_count",
        "non_default_output_count",
        "decision_change_count",
        "direction_change_count",
        "abstention_change_count",
        "selection_change_count",
        "historical_paired_delta_bps",
        "uncertainty_bps",
        "dependence_adjusted_world_count",
    ):
        assert key in payload
