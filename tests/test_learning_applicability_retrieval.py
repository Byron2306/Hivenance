from strategies.relative_value_lab.learning_applicability import (
    LiveResearchContext,
)
from strategies.relative_value_lab.learning_memory import (
    add_learning_receipt,
)
from strategies.relative_value_lab.learning_retrieval import (
    applicability_learning_brief,
)
from strategies.relative_value_lab.world_graph import (
    WorldGraph,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


ROOT = "sha256:" + "a" * 64


def graph():
    observation = ScoreObservation(
        observation_id="obs",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1001,
        evidence_root=ROOT,
        payload={"price": 100.0},
    )

    frame = CanonicalWorldScore.assemble(
        observations=(observation,),
        assembled_at_ms=5000,
        freshness_window_ms=10000,
    )

    return WorldGraph(frame)


def context(**overrides):
    values = dict(
        model_id="model-A",
        symbol="BTC/USD",
        horizon_seconds=300,
        forecast_id="forecast-live",
        hypothesis_family="breakout",
        direction="UP",
        regime="TREND",
        world_state_id="live-world",
        evidence_roots=(ROOT,),
        asof_ms=5000,
    )

    values.update(overrides)

    return LiveResearchContext(
        **values
    )


def receipt(
    learning_id,
    *,
    symbol="BTC/USD",
    model_id="model-A",
    horizon_seconds=300,
    direction="UP",
    regime="TREND",
    state="SUPPORTED",
    settled_at_ms=2000,
    superseded=False,
):
    return {
        "schema":
            "hivenance_learning_receipt_v2",
        "learning_id": learning_id,
        "authority":
            "PROSPECTIVE_RESEARCH_ONLY",
        "execution_eligible": False,
        "promotion_eligible": False,

        "learning_state": state,
        "superseded": superseded,

        "applicability": {
            "model_id": model_id,
            "symbol": symbol,
            "horizon_seconds":
                horizon_seconds,
            "hypothesis_family":
                "breakout",
            "direction": direction,
            "regime": regime,
            "world_state_ids": (
                "historical-world",
            ),
            "evidence_roots": (
                ROOT,
            ),
            "observed_at_ms": 1000,
            "settled_at_ms":
                settled_at_ms,
        },

        "source_artifacts": [
            {
                "sha256": "a" * 64,
            }
        ],

        "interpretation": {
            "supported":
                f"claim:{learning_id}",
            "contradicted":
                f"contradiction:{learning_id}",
        },

        "next_falsification": (
            f"challenge:{learning_id}",
        ),
    }


def test_only_exactly_applicable_learning_enters_active_brief():
    g = graph()

    add_learning_receipt(
        g,
        receipt("match"),
        created_at_ms=3000,
    )

    add_learning_receipt(
        g,
        receipt(
            "wrong-symbol",
            symbol="ETH/USD",
        ),
        created_at_ms=3001,
    )

    brief = applicability_learning_brief(
        g.queen_view(created_at_ms=5000),
        context=context(),
    )

    assert brief.applicable_learning_ids == (
        "match",
    )

    assert brief.supported_learning_ids == (
        "match",
    )

    assert brief.rejected_learning_ids == (
        "wrong-symbol",
    )

    assert "claim:match" in (
        brief.supported_claims
    )

    assert "claim:wrong-symbol" not in (
        brief.supported_claims
    )


def test_wrong_model_horizon_and_direction_are_visible_but_not_influential():
    g = graph()

    add_learning_receipt(
        g,
        receipt(
            "wrong-model",
            model_id="model-B",
        ),
        created_at_ms=3000,
    )

    add_learning_receipt(
        g,
        receipt(
            "wrong-horizon",
            horizon_seconds=3600,
        ),
        created_at_ms=3001,
    )

    add_learning_receipt(
        g,
        receipt(
            "wrong-direction",
            direction="DOWN",
        ),
        created_at_ms=3002,
    )

    brief = applicability_learning_brief(
        g.queen_view(created_at_ms=5000),
        context=context(),
    )

    assert brief.applicable_learning_ids == ()

    assert set(
        brief.rejected_learning_ids
    ) == {
        "wrong-model",
        "wrong-horizon",
        "wrong-direction",
    }


def test_applicable_negative_learning_is_preserved_as_contradiction():
    g = graph()

    add_learning_receipt(
        g,
        receipt(
            "negative",
            state="CONTRADICTED",
        ),
        created_at_ms=3000,
    )

    brief = applicability_learning_brief(
        g.queen_view(created_at_ms=5000),
        context=context(),
    )

    assert brief.applicable_learning_ids == (
        "negative",
    )

    assert (
        brief.contradicted_learning_ids
        == ("negative",)
    )

    assert (
        "contradiction:negative"
        in brief.contradictions
    )

    assert brief.execution_eligible is False
    assert brief.promotion_eligible is False


def test_decayed_learning_is_reported_but_not_influential():
    g = graph()

    add_learning_receipt(
        g,
        receipt(
            "old",
            settled_at_ms=1000,
        ),
        created_at_ms=2000,
    )

    brief = applicability_learning_brief(
        g.queen_view(created_at_ms=10000),
        context=context(
            asof_ms=10000
        ),
        max_age_ms=5000,
    )

    assert brief.applicable_learning_ids == ()

    assert brief.decayed_learning_ids == (
        "old",
    )


def test_superseded_learning_is_reported_but_not_influential():
    g = graph()

    add_learning_receipt(
        g,
        receipt(
            "old-thesis",
            superseded=True,
        ),
        created_at_ms=3000,
    )

    brief = applicability_learning_brief(
        g.queen_view(created_at_ms=5000),
        context=context(),
    )

    assert brief.applicable_learning_ids == ()

    assert (
        brief.superseded_learning_ids
        == ("old-thesis",)
    )


def test_regime_specific_learning_cannot_cross_regime():
    g = graph()

    add_learning_receipt(
        g,
        receipt(
            "trend-only",
            regime="TREND",
        ),
        created_at_ms=3000,
    )

    brief = applicability_learning_brief(
        g.queen_view(created_at_ms=5000),
        context=context(
            regime="CHOP"
        ),
    )

    assert brief.applicable_learning_ids == ()

    assert brief.rejected_learning_ids == (
        "trend-only",
    )


def test_incomplete_legacy_memory_is_not_silently_promoted():
    g = graph()

    legacy = {
        "schema":
            "hivenance_learning_receipt_v1",
        "learning_id": "legacy",
        "authority":
            "HISTORICAL_DISCOVERY_ONLY",
        "execution_eligible": False,
        "promotion_eligible": False,
        "source_artifacts": [
            {
                "sha256": "b" * 64,
            }
        ],
        "interpretation": {
            "supported":
                "interesting historical scar",
        },
    }

    add_learning_receipt(
        g,
        legacy,
        created_at_ms=3000,
    )

    brief = applicability_learning_brief(
        g.queen_view(created_at_ms=5000),
        context=context(),
    )

    assert brief.applicable_learning_ids == ()

    assert brief.incomplete_learning_ids == (
        "legacy",
    )

    assert (
        "interesting historical scar"
        not in brief.supported_claims
    )
