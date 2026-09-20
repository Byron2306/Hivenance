from strategies.relative_value_lab.historical_phoenix_replay import (
    frame_from_reconstruction,
    replay_historical_phoenix,
)
from strategies.relative_value_lab.historical_reconstruction_input import (
    reconstruction_input_from_case,
)
from tests.test_historical_reconstruction_input import (
    case,
)


def test_frame_preserves_original_world_binding():
    inp = reconstruction_input_from_case(
        case()
    )

    frame = frame_from_reconstruction(
        inp
    )

    assert (
        frame.world_state_id
        == inp.world_state_id
    )

    assert (
        frame.world_state_hash
        == inp.world_state_hash
    )


def test_frame_contains_only_predecision_observation():
    inp = reconstruction_input_from_case(
        case()
    )

    frame = frame_from_reconstruction(
        inp
    )

    rendered = repr(
        frame.to_dict()
    )

    assert "exit_price" not in rendered
    assert (
        "realized_roundtrip_cost_bps"
        not in rendered
    )

    assert (
        "net_opportunity_bps"
        not in rendered
    )


def test_real_phoenix_competition_runs():
    inp = reconstruction_input_from_case(
        case()
    )

    replay = replay_historical_phoenix(
        inp
    )

    assert replay.forecasts_total > 0

    assert (
        replay.forecasts_total
        == (
            replay.non_abstain_forecasts
            + replay.abstentions
        )
    )


def test_synthesis_context_reaches_real_feature():
    inp = reconstruction_input_from_case(
        case()
    )

    replay = replay_historical_phoenix(
        inp
    )

    ctx = replay.synthesis_feature.values[
        "synthesis_context"
    ]

    assert (
        ctx["world_state_id"]
        == inp.world_state_id
    )

    assert (
        ctx["world_state_hash"]
        == inp.world_state_hash
    )


def test_replay_never_grants_execution_authority():
    inp = reconstruction_input_from_case(
        case()
    )

    replay = replay_historical_phoenix(
        inp
    )

    assert replay.execution_eligible is False
    assert replay.promotion_eligible is False

    assert all(
        not f.execution_eligible
        for f in replay.forecasts
    )
