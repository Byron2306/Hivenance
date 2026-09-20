import pytest

from strategies.relative_value_lab.historical_mask_engine import (
    historical_mask_plan,
)
from strategies.relative_value_lab.historical_middle_mask_bridge import (
    deterministic_control_direction,
    prepare_middle_replay,
    simple_control_direction,
)


def context():
    return {
        "long_horizon_lattice":
            {"7d": 1, "30d": 2},
        "cex_oracle":
            {"1h": "UP"},
        "coin_selector":
            {"selected": ("BTC/USD",)},
        "regime":
            {"state": "TREND"},
        "worker_proposals":
            ({"id": "w1"},),
        "worker_coalition":
            {"id": "wc1"},
        "positive_crystals":
            ({"id": "pc1"},),
        "negative_crystals":
            ({"id": "nc1"},),
        "control_returns":
            (.01, .02, -.005),
    }


@pytest.mark.parametrize(
    "mask,key",
    [
        (
            "NO_LONG_HORIZON_LATTICE",
            "long_horizon_lattice",
        ),
        (
            "NO_CEX_ORACLE",
            "cex_oracle",
        ),
        (
            "NO_COIN_SELECTOR",
            "coin_selector",
        ),
        (
            "NO_REGIME",
            "regime",
        ),
    ],
)
def test_single_context_masks_remove_only_target(
    mask,
    key,
):
    original = context()

    out = prepare_middle_replay(
        mask=historical_mask_plan(
            mask
        ),
        context=original,
    )

    assert out.context[key] is None


def test_no_workers_removes_proposals_and_coalition():
    out = prepare_middle_replay(
        mask=historical_mask_plan(
            "NO_WORKERS"
        ),
        context=context(),
    )

    assert (
        out.context["worker_proposals"]
        == ()
    )

    assert (
        out.context["worker_coalition"]
        is None
    )


def test_no_crystals_removes_both_memory_polarities():
    out = prepare_middle_replay(
        mask=historical_mask_plan(
            "NO_CRYSTALS"
        ),
        context=context(),
    )

    assert (
        out.context["positive_crystals"]
        == ()
    )

    assert (
        out.context["negative_crystals"]
        == ()
    )


@pytest.mark.parametrize(
    "mask",
    [
        "SIMPLE_MOMENTUM",
        "SIMPLE_REVERSION",
        "DETERMINISTIC_RANDOM",
    ],
)
def test_control_model_substitution_survives(
    mask,
):
    out = prepare_middle_replay(
        mask=historical_mask_plan(
            mask
        ),
        context=context(),
    )

    assert (
        out.model_substitution
        == mask
    )


def test_no_trade_forces_no_trade():
    out = prepare_middle_replay(
        mask=historical_mask_plan(
            "NO_TRADE"
        ),
        context=context(),
    )

    assert out.force_no_trade is True


def test_simple_momentum_uses_only_declared_control_returns():
    direction = simple_control_direction(
        model_substitution=(
            "SIMPLE_MOMENTUM"
        ),
        context={
            "control_returns":
                (.01, .02, -.005),
        },
        world_state_hash=(
            "sha256:" + "a" * 64
        ),
    )

    assert direction == "UP"


def test_simple_reversion_inverts_same_simple_signal():
    direction = simple_control_direction(
        model_substitution=(
            "SIMPLE_REVERSION"
        ),
        context={
            "control_returns":
                (.01, .02, -.005),
        },
        world_state_hash=(
            "sha256:" + "a" * 64
        ),
    )

    assert direction == "DOWN"


def test_simple_control_abstains_without_input_history():
    assert (
        simple_control_direction(
            model_substitution=(
                "SIMPLE_MOMENTUM"
            ),
            context={},
            world_state_hash=(
                "sha256:" + "a" * 64
            ),
        )
        == "ABSTAIN"
    )


def test_deterministic_random_is_repeatable_for_world():
    root = (
        "sha256:" + "a" * 64
    )

    first = (
        deterministic_control_direction(
            model_substitution=(
                "DETERMINISTIC_RANDOM"
            ),
            world_state_hash=root,
        )
    )

    second = (
        deterministic_control_direction(
            model_substitution=(
                "DETERMINISTIC_RANDOM"
            ),
            world_state_hash=root,
        )
    )

    assert first == second

    assert first in {
        "UP",
        "DOWN",
    }


def test_middle_bridge_never_grants_authority():
    out = prepare_middle_replay(
        mask=historical_mask_plan(
            "NO_REGIME"
        ),
        context=context(),
    )

    assert out.execution_eligible is False
    assert out.promotion_eligible is False
