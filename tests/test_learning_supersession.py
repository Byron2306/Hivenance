from strategies.relative_value_lab.learning_supersession import (
    resolve_learning_supersession,
)


ROOT = "sha256:" + "a" * 64


def receipt(
    learning_id,
    *,
    settled_at_ms,
    symbol="BTC/USD",
    model_id="model-A",
):
    return {
        "learning_id": learning_id,
        "applicability": {
            "model_id": model_id,
            "symbol": symbol,
            "horizon_seconds": 300,
            "hypothesis_family": "breakout",
            "direction": "UP",
            "regime": "TREND",
            "world_state_ids": ("w1",),
            "evidence_roots": (ROOT,),
            "observed_at_ms": 1000,
            "settled_at_ms": settled_at_ms,
        },
    }


def test_newer_learning_supersedes_same_scope():
    out = resolve_learning_supersession((
        receipt("old", settled_at_ms=2000),
        receipt("new", settled_at_ms=3000),
    ))

    assert out.superseded_learning_ids == (
        "old",
    )

    assert out.surviving_learning_ids == (
        "new",
    )

    assert len(out.records) == 1

    assert (
        out.records[0].older_learning_id
        == "old"
    )

    assert (
        out.records[0].newer_learning_id
        == "new"
    )


def test_different_symbol_does_not_supersede():
    out = resolve_learning_supersession((
        receipt(
            "btc",
            settled_at_ms=2000,
            symbol="BTC/USD",
        ),
        receipt(
            "eth",
            settled_at_ms=3000,
            symbol="ETH/USD",
        ),
    ))

    assert out.superseded_learning_ids == ()

    assert set(
        out.surviving_learning_ids
    ) == {"btc", "eth"}


def test_different_model_does_not_supersede():
    out = resolve_learning_supersession((
        receipt(
            "a",
            settled_at_ms=2000,
            model_id="model-A",
        ),
        receipt(
            "b",
            settled_at_ms=3000,
            model_id="model-B",
        ),
    ))

    assert out.superseded_learning_ids == ()


def test_supersession_remains_research_only():
    out = resolve_learning_supersession((
        receipt("old", settled_at_ms=2000),
        receipt("new", settled_at_ms=3000),
    ))

    assert out.execution_eligible is False
    assert out.promotion_eligible is False
