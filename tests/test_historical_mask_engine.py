import pytest

from strategies.relative_value_lab.historical_causal_prosecution import (
    PAIRED_MASKS,
)
from strategies.relative_value_lab.historical_mask_engine import (
    all_historical_mask_plans,
    assert_no_envelope_mutation_counterfactual,
    historical_mask_plan,
)


def test_every_frozen_phase12_mask_has_exactly_one_plan():
    plans = (
        all_historical_mask_plans()
    )

    assert tuple(
        x.mask_id
        for x in plans
    ) == PAIRED_MASKS

    assert len(
        {
            x.plan_id
            for x in plans
        }
    ) == len(PAIRED_MASKS)


def test_full_hive_disables_nothing():
    plan = historical_mask_plan(
        "FULL_HIVE"
    )

    assert plan.disabled_organs == ()
    assert plan.disabled_channels == ()
    assert (
        plan.disabled_evidence_families
        == ()
    )

    assert plan.model_substitution is None
    assert plan.force_no_trade is False


@pytest.mark.parametrize(
    "mask,family",
    [
        ("NO_FLOW", "FLOW"),
        ("NO_LIQUIDITY", "LIQUIDITY"),
        ("NO_VOLATILITY", "VOLATILITY"),
        ("NO_CROSS_MARKET", "CROSS_MARKET"),
        (
            "NO_TEMPORAL_PARTICIPATION",
            "TEMPORAL_PARTICIPATION",
        ),
        ("NO_REGIME", "REGIME"),
        ("NO_LEARNING", "LEARNING"),
    ],
)
def test_evidence_family_masks_are_explicit(
    mask,
    family,
):
    plan = historical_mask_plan(
        mask
    )

    assert (
        family
        in plan.disabled_evidence_families
    )


@pytest.mark.parametrize(
    "mask,organ",
    [
        (
            "NO_COMPARISON",
            "comparison_engine",
        ),
        (
            "NO_COIN_SELECTOR",
            "coin_selector",
        ),
        (
            "NO_WORKERS",
            "workers",
        ),
        (
            "NO_CRYSTALS",
            "crystals",
        ),
        (
            "NO_LEARNING",
            "learning_memory",
        ),
        (
            "NO_QUORUM",
            "polyphonic_quorum",
        ),
        (
            "NO_QUEEN",
            "conducting_queen",
        ),
        (
            "NO_MYSTIQUE",
            "mystique",
        ),
        (
            "NO_METABOLISM",
            "cognitive_metabolism",
        ),
        (
            "NO_POLLEN",
            "pollen_economy",
        ),
    ],
)
def test_organ_masks_are_explicit(
    mask,
    organ,
):
    assert organ in (
        historical_mask_plan(
            mask
        ).disabled_organs
    )


@pytest.mark.parametrize(
    "mask,model",
    [
        (
            "SIMPLE_MOMENTUM",
            "SIMPLE_MOMENTUM",
        ),
        (
            "SIMPLE_REVERSION",
            "SIMPLE_REVERSION",
        ),
        (
            "DETERMINISTIC_RANDOM",
            "DETERMINISTIC_RANDOM",
        ),
    ],
)
def test_control_models_are_explicit_substitutions(
    mask,
    model,
):
    plan = historical_mask_plan(
        mask
    )

    assert (
        plan.model_substitution
        == model
    )


def test_no_trade_is_explicit():
    plan = historical_mask_plan(
        "NO_TRADE"
    )

    assert plan.force_no_trade is True


def test_every_mask_requires_fresh_historical_replay():
    assert all(
        p.requires_fresh_replay
        and p.preserves_observed_world
        for p in (
            all_historical_mask_plans()
        )
    )


def test_frozen_envelope_cannot_be_edited_into_counterfactual():
    with pytest.raises(
        ValueError,
        match="runtime_replay_not_envelope_mutation",
    ):
        assert_no_envelope_mutation_counterfactual(
            source_envelope_id=(
                "henv_full"
            ),
            requested_mask_id=(
                "NO_QUEEN"
            ),
        )


def test_unknown_mask_refuses():
    with pytest.raises(
        ValueError,
        match="unknown_historical_mask",
    ):
        historical_mask_plan(
            "NO_MAGIC"
        )
