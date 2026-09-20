from strategies.relative_value_lab.crystal_applicability import (
    evaluate_crystal_applicability,
)
from strategies.relative_value_lab.learning_applicability import (
    LiveResearchContext,
)


ROOT = "sha256:" + "a" * 64


def context(**overrides):
    values = dict(
        model_id="model-A",
        symbol="BTC/USD",
        horizon_seconds=300,
        forecast_id="f-live",
        hypothesis_family="breakout",
        direction="UP",
        regime="TREND",
        world_state_id="world-live",
        evidence_roots=(ROOT,),
        asof_ms=5000,
    )

    values.update(overrides)

    return LiveResearchContext(**values)


def crystal(
    crystal_id,
    kind,
    **overrides,
):
    applicability = dict(
        model_id="model-A",
        symbol="BTC/USD",
        horizon_seconds=300,
        hypothesis_family="breakout",
        direction="UP",
        regime="TREND",
        world_state_ids=("historical-world",),
        evidence_roots=(ROOT,),
        observed_at_ms=1000,
        settled_at_ms=2000,
    )

    applicability.update(overrides)

    return {
        "crystal_id": crystal_id,
        "crystal_kind": kind,
        "applicability": applicability,
        "execution_eligible": False,
        "promotion_eligible": False,
    }


def test_matching_positive_crystal_is_context_only():
    out = evaluate_crystal_applicability(
        crystal=crystal(
            "positive-1",
            "POSITIVE_THESIS",
        ),
        context=context(),
    )

    assert out.applicable is True
    assert out.effect == "CONTEXT_ONLY"

    assert out.execution_eligible is False
    assert out.promotion_eligible is False


def test_matching_negative_crystal_is_veto_eligible():
    out = evaluate_crystal_applicability(
        crystal=crystal(
            "negative-1",
            "NEGATIVE_CAPABILITY",
        ),
        context=context(),
    )

    assert out.applicable is True
    assert out.effect == "VETO_ELIGIBLE"


def test_wrong_symbol_negative_crystal_cannot_veto():
    out = evaluate_crystal_applicability(
        crystal=crystal(
            "negative-1",
            "NEGATIVE_CAPABILITY",
        ),
        context=context(
            symbol="ETH/USD",
        ),
    )

    assert out.applicable is False
    assert out.effect == "NO_INFLUENCE"


def test_wrong_horizon_negative_crystal_cannot_veto():
    out = evaluate_crystal_applicability(
        crystal=crystal(
            "negative-1",
            "NEGATIVE_CAPABILITY",
        ),
        context=context(
            horizon_seconds=3600,
        ),
    )

    assert out.applicable is False
    assert out.effect == "NO_INFLUENCE"


def test_wrong_direction_negative_crystal_cannot_veto():
    out = evaluate_crystal_applicability(
        crystal=crystal(
            "negative-1",
            "NEGATIVE_CAPABILITY",
        ),
        context=context(
            direction="DOWN",
        ),
    )

    assert out.applicable is False
    assert out.effect == "NO_INFLUENCE"


def test_decayed_crystal_has_no_influence():
    out = evaluate_crystal_applicability(
        crystal=crystal(
            "old-crystal",
            "NEGATIVE_CAPABILITY",
        ),
        context=context(
            asof_ms=20000,
        ),
        max_age_ms=5000,
    )

    assert out.applicable is False
    assert out.effect == "NO_INFLUENCE"

    assert (
        out.applicability.state
        == "DECAYED"
    )


def test_superseded_crystal_has_no_influence():
    item = crystal(
        "superseded",
        "NEGATIVE_CAPABILITY",
    )

    item["superseded"] = True

    out = evaluate_crystal_applicability(
        crystal=item,
        context=context(),
    )

    assert out.applicable is False
    assert out.effect == "NO_INFLUENCE"

    assert (
        out.applicability.state
        == "SUPERSEDED"
    )
