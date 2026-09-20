from dataclasses import replace

import pytest

from strategies.relative_value_lab.historical_reconstruction_input import (
    HistoricalReconstructionInput,
    reconstruction_input_from_case,
)
from strategies.relative_value_lab.historical_real_corpus import (
    HistoricalCorpusCase,
)


def case():
    return HistoricalCorpusCase(
        case_id="c1",
        freeze_id="f1",
        settlement_id="s1",
        observation_run_id="obs1",
        symbol="BTC/USD",
        selected=True,
        selector_rank=1,
        blind_rank=5,
        blind_selected=False,
        observed_ts=1000.0,
        target_ts=1300.0,
        settled_ts=1301.0,
        horizon_seconds=300,
        world_state_id="ws1",
        world_state_hash=(
            "sha256:" + "a" * 64
        ),
        evidence_root=(
            "sha256:" + "b" * 64
        ),
        entry_price=100.0,
        exit_price=102.0,
        predicted_roundtrip_cost_bps=12.0,
        net_opportunity_bps=180.0,
        gross_absolute_move_bps=200.0,
        regime="trend_expansion",
        freeze_payload={
            "observed_at_ms":
                1_000_000,
            "selector_score":
                .91,
        },
        settlement_payload={
            "exit_price": 102.0,
            "realized_roundtrip_cost_bps":
                20.0,
        },
        observation_snapshot={
            "_historical_source_table":
                "observation_universe_snapshots",
            "id": 123,
            "run_id": "obs1",
            "ts": 999.0,
            "venue": "kraken",
            "symbol": "BTC/USD",
            "price": 100.0,
            "spread_bps": 2.0,
            "depth_usd_25bps": 500000.0,
            "volatility_expansion": 1.2,
            "volume_zscore": .8,
            "book_imbalance": .1,
            "data_quality": 1.0,
            "execution_eligible": 0,
            "payload": "{}",
        },
        matching_forecasts=(),
        matching_outcomes=(),
    )


def test_builds_predecision_reconstruction_input():
    out = reconstruction_input_from_case(
        case()
    )

    assert out.symbol == "BTC/USD"

    assert (
        out.observation_source
        == "observation_universe_snapshots"
    )

    assert (
        out.selector_state[
            "selector_rank"
        ]
        == 1
    )

    assert (
        out.cost_state[
            "predicted_roundtrip_cost_bps"
        ]
        == pytest.approx(12.0)
    )


def test_settlement_information_is_not_copied():
    out = reconstruction_input_from_case(
        case()
    )

    rendered = repr(
        out.to_dict()
    )

    assert "exit_price" not in rendered
    assert "net_opportunity_bps" not in rendered
    assert (
        "realized_roundtrip_cost_bps"
        not in rendered
    )


def test_historical_hypothesis_context_is_correctly_absent():
    out = reconstruction_input_from_case(
        case()
    )

    assert (
        out.historical_hypothesis_context_available
        is False
    )

    assert (
        out.historical_outcome_context_available
        is False
    )


def test_future_key_in_observation_is_refused():
    c = case()

    poisoned = replace(
        c,
        observation_snapshot={
            **c.observation_snapshot,
            "exit_price": 102.0,
        },
    )

    with pytest.raises(
        ValueError,
        match="future_leak",
    ):
        reconstruction_input_from_case(
            poisoned
        )


def test_nested_future_key_is_refused():
    c = case()

    poisoned = replace(
        c,
        observation_snapshot={
            **c.observation_snapshot,
            "payload": {
                "values": {
                    "net_return_bps":
                        99.0,
                }
            },
        },
    )

    with pytest.raises(
        ValueError,
        match="future_leak",
    ):
        reconstruction_input_from_case(
            poisoned
        )


def test_wrong_horizon_is_refused():
    out = reconstruction_input_from_case(
        case()
    )

    with pytest.raises(
        ValueError,
        match="horizon_mismatch",
    ):
        HistoricalReconstructionInput(
            **{
                **out.__dict__,
                "target_at_ms":
                    out.target_at_ms
                    + 1000,
            }
        )


def test_no_authority_is_ever_granted():
    out = reconstruction_input_from_case(
        case()
    )

    assert out.execution_eligible is False
    assert out.promotion_eligible is False
