from strategies.relative_value_lab.historical_matrix_aggregation import (
    MASK_TO_ORGAN,
    aggregate_historical_matrix,
)
from tests.test_historical_prosecution_matrix import (
    case,
    replay,
)
from strategies.relative_value_lab.historical_prosecution_matrix import (
    run_historical_matrix_case,
)


def test_matrix_aggregation_produces_every_organ_row():
    cases = tuple(
        run_historical_matrix_case(
            case=case(),
            replay_mask=replay,
        )
        for _ in range(6)
    )

    organs = set(
        MASK_TO_ORGAN.values()
    )

    availability = {
        x: True
        for x in organs
    }

    invoked = {
        x: 6
        for x in organs
    }

    non_default = {
        x: 6
        for x in organs
    }

    result = aggregate_historical_matrix(
        cases=cases,
        availability=availability,
        invocation_counts=invoked,
        non_default_output_counts=(
            non_default
        ),
        minimum_paired_worlds=5,
    )

    assert len(
        result.organ_results
    ) == len(MASK_TO_ORGAN)

    assert set(
        x.organ_id
        for x in result.organ_results
    ) == organs

    assert (
        result.receipt.historical_only
        is True
    )

    assert (
        result.receipt.prospective_usefulness_proven
        is False
    )


def test_controls_are_counted_but_not_mislabeled_as_organs():
    cases = (
        run_historical_matrix_case(
            case=case(),
            replay_mask=replay,
        ),
    )

    result = aggregate_historical_matrix(
        cases=cases,
        availability={},
        invocation_counts={},
        non_default_output_counts={},
        minimum_paired_worlds=5,
    )

    assert (
        result.control_mask_pair_counts[
            "SIMPLE_MOMENTUM"
        ]
        == 1
    )

    assert (
        result.control_mask_pair_counts[
            "SIMPLE_REVERSION"
        ]
        == 1
    )

    assert (
        result.control_mask_pair_counts[
            "DETERMINISTIC_RANDOM"
        ]
        == 1
    )

    assert (
        result.control_mask_pair_counts[
            "NO_TRADE"
        ]
        == 1
    )


def test_matrix_aggregate_never_claims_prospective_utility():
    cases = tuple(
        run_historical_matrix_case(
            case=case(),
            replay_mask=replay,
        )
        for _ in range(6)
    )

    result = aggregate_historical_matrix(
        cases=cases,
        availability={
            x: True
            for x in (
                MASK_TO_ORGAN.values()
            )
        },
        invocation_counts={
            x: 6
            for x in (
                MASK_TO_ORGAN.values()
            )
        },
        non_default_output_counts={
            x: 6
            for x in (
                MASK_TO_ORGAN.values()
            )
        },
    )

    assert (
        result.receipt.prospective_usefulness_proven
        is False
    )

    assert result.execution_eligible is False
    assert result.promotion_eligible is False
