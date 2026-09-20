from strategies.relative_value_lab.historical_mask_application import (
    HistoricalReplayConfig,
    apply_mask_to_replay_config,
    filter_evidence_families,
)
from strategies.relative_value_lab.historical_mask_engine import (
    historical_mask_plan,
)


def test_mask_application_preserves_existing_disabled_organs():
    base = HistoricalReplayConfig(
        disabled_organs=(
            "already_disabled",
        )
    )

    out = apply_mask_to_replay_config(
        base=base,
        mask=historical_mask_plan(
            "NO_QUEEN"
        ),
    )

    assert set(
        out.disabled_organs
    ) == {
        "already_disabled",
        "conducting_queen",
    }


def test_flow_mask_filters_only_flow_family():
    evidence = (
        {"family": "FLOW", "id": 1},
        {
            "family": "LIQUIDITY",
            "id": 2,
        },
        {
            "family": "VOLATILITY",
            "id": 3,
        },
    )

    plan = historical_mask_plan(
        "NO_FLOW"
    )

    config = apply_mask_to_replay_config(
        base=HistoricalReplayConfig(),
        mask=plan,
    )

    out = filter_evidence_families(
        evidence,
        disabled_families=(
            config.disabled_evidence_families
        ),
    )

    assert tuple(
        x["family"]
        for x in out
    ) == (
        "LIQUIDITY",
        "VOLATILITY",
    )


def test_model_control_substitution_is_carried():
    out = apply_mask_to_replay_config(
        base=HistoricalReplayConfig(),
        mask=historical_mask_plan(
            "SIMPLE_MOMENTUM"
        ),
    )

    assert (
        out.model_substitution
        == "SIMPLE_MOMENTUM"
    )


def test_no_trade_survives_configuration():
    out = apply_mask_to_replay_config(
        base=HistoricalReplayConfig(),
        mask=historical_mask_plan(
            "NO_TRADE"
        ),
    )

    assert out.force_no_trade is True


def test_mask_application_never_grants_authority():
    out = apply_mask_to_replay_config(
        base=HistoricalReplayConfig(),
        mask=historical_mask_plan(
            "NO_POLLEN"
        ),
    )

    assert out.historical_only is True
    assert out.execution_eligible is False
    assert out.promotion_eligible is False
