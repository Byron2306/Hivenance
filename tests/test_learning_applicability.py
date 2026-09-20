from strategies.relative_value_lab.learning_applicability import (
    LearningApplicability,
    LiveResearchContext,
    applicability_from_receipt,
    evaluate_learning_applicability,
)


ROOT = "sha256:" + "a" * 64


def memory(**overrides):
    values = dict(
        model_id="model-A",
        symbol="BTC/USD",
        horizon_seconds=300,
        forecast_id=None,
        hypothesis_family="breakout",
        direction="UP",
        regime="TREND",
        world_state_ids=("historical-world",),
        evidence_roots=(ROOT,),
        observed_at_ms=1000,
        settled_at_ms=2000,
    )
    values.update(overrides)
    return LearningApplicability(**values)


def live(**overrides):
    values = dict(
        model_id="model-A",
        symbol="BTC/USD",
        horizon_seconds=300,
        forecast_id="forecast-live",
        hypothesis_family="breakout",
        direction="UP",
        regime="TREND",
        world_state_id="world-live",
        evidence_roots=(ROOT,),
        asof_ms=5000,
    )
    values.update(overrides)
    return LiveResearchContext(**values)


def decide(
    applicability=None,
    context=None,
    **kwargs,
):
    return evaluate_learning_applicability(
        learning_id="learning-1",
        applicability=(
            applicability or memory()
        ),
        context=(context or live()),
        **kwargs,
    )


def test_exact_learning_scope_is_applicable():
    result = decide()

    assert result.applicable is True
    assert result.state == "SUPPORTED"

    assert result.mismatched_fields == ()
    assert result.missing_fields == ()

    assert result.execution_eligible is False
    assert result.promotion_eligible is False


def test_wrong_symbol_cannot_apply():
    result = decide(
        context=live(symbol="ETH/USD")
    )

    assert result.applicable is False
    assert result.state == "NOT_APPLICABLE"
    assert "symbol" in result.mismatched_fields


def test_wrong_model_cannot_apply():
    result = decide(
        context=live(model_id="model-B")
    )

    assert result.applicable is False
    assert "model_id" in result.mismatched_fields


def test_wrong_horizon_cannot_apply():
    result = decide(
        context=live(horizon_seconds=3600)
    )

    assert result.applicable is False
    assert (
        "horizon_seconds"
        in result.mismatched_fields
    )


def test_wrong_direction_cannot_apply():
    result = decide(
        context=live(direction="DOWN")
    )

    assert result.applicable is False
    assert "direction" in result.mismatched_fields


def test_wrong_regime_cannot_apply_regime_specific_learning():
    result = decide(
        context=live(regime="CHOP")
    )

    assert result.applicable is False
    assert "regime" in result.mismatched_fields


def test_matching_negative_learning_can_be_applicable():
    result = decide(
        declared_state="CONTRADICTED"
    )

    assert result.applicable is True
    assert result.state == "CONTRADICTED"

    assert result.execution_eligible is False
    assert result.promotion_eligible is False


def test_positive_learning_never_gains_execution_authority():
    result = decide(
        declared_state="SUPPORTED"
    )

    assert result.applicable is True
    assert result.state == "SUPPORTED"

    assert result.execution_eligible is False
    assert result.promotion_eligible is False


def test_future_settlement_cannot_apply():
    result = decide(
        applicability=memory(
            settled_at_ms=6000,
        )
    )

    assert result.applicable is False
    assert result.state == "NOT_APPLICABLE"

    assert (
        "settled_at_ms_future"
        in result.mismatched_fields
    )


def test_missing_scope_fails_closed():
    result = decide(
        applicability=memory(
            model_id=None,
        )
    )

    assert result.applicable is False
    assert result.state == "INCOMPLETE"

    assert "model_id" in result.missing_fields


def test_old_learning_decays():
    result = decide(
        context=live(asof_ms=20000),
        max_age_ms=5000,
    )

    assert result.applicable is False
    assert result.state == "DECAYED"


def test_superseded_learning_cannot_apply():
    result = decide(
        superseded=True
    )

    assert result.applicable is False
    assert result.state == "SUPERSEDED"


def test_forecast_specific_learning_cannot_cross_forecasts():
    result = decide(
        applicability=memory(
            forecast_id="forecast-old",
            hypothesis_family=None,
        )
    )

    assert result.applicable is False
    assert "forecast_id" in result.mismatched_fields


def test_receipt_parser_does_not_invent_missing_scope():
    receipt = {
        "learning_id": "old-learning",
        "model_id": "model-A",
        "symbol": "BTC/USD",
        "horizon_seconds": 300,
        "direction": "UP",
        "source_artifacts": [
            {
                "sha256": "a" * 64,
            }
        ],
        "observed_at_ms": 1000,
        "settled_at_ms": 2000,
    }

    parsed = applicability_from_receipt(
        receipt
    )

    assert parsed.model_id == "model-A"
    assert parsed.symbol == "BTC/USD"
    assert parsed.evidence_roots == (ROOT,)

    assert parsed.forecast_id is None
    assert parsed.hypothesis_family is None
    assert parsed.regime is None
