from strategies.relative_value_lab.historical_feature_reconstruction import (
    feature_from_reconstruction,
)
from strategies.relative_value_lab.historical_reconstruction_input import (
    reconstruction_input_from_case,
)
from tests.test_historical_reconstruction_input import (
    case,
)


def test_reconstructs_feature_from_frozen_observation():
    inp = reconstruction_input_from_case(
        case()
    )

    f = feature_from_reconstruction(
        inp
    )

    assert f.symbol == "BTC/USD"
    assert f.timestamp_ms == 1_000_000

    assert f.price == 100.0
    assert f.spread_bps == 2.0

    assert (
        f.depth_usd_25bps
        == 500000.0
    )

    assert (
        f.book_imbalance
        == .1
    )


def test_reconstruction_metadata_is_explicit():
    inp = reconstruction_input_from_case(
        case()
    )

    f = feature_from_reconstruction(
        inp
    )

    meta = f.values[
        "historical_reconstruction"
    ]

    assert (
        meta[
            "retrospective_reconstruction_only"
        ]
        is True
    )

    assert (
        meta["execution_eligible"]
        is False
    )


def test_world_binding_is_preserved_for_synthesis_bridge():
    inp = reconstruction_input_from_case(
        case()
    )

    f = feature_from_reconstruction(
        inp
    )

    assert (
        f.values["world_state_id"]
        == inp.world_state_id
    )


def test_missing_feature_is_not_invented():
    inp = reconstruction_input_from_case(
        case()
    )

    f = feature_from_reconstruction(
        inp
    )

    assert (
        f.order_flow_imbalance
        is None
    )

    assert (
        f.trade_count_zscore
        is None
    )


def test_settlement_truth_never_enters_feature():
    inp = reconstruction_input_from_case(
        case()
    )

    f = feature_from_reconstruction(
        inp
    )

    rendered = repr(f)

    assert "exit_price" not in rendered
    assert (
        "net_opportunity_bps"
        not in rendered
    )

    assert (
        "realized_roundtrip_cost_bps"
        not in rendered
    )
