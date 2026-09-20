from strategies.relative_value_lab.historical_forecast_outcome import (
    forecast_outcome_on_real_tape,
)
from strategies.relative_value_lab.historical_real_corpus import (
    HistoricalRealCorpus,
)
from strategies.relative_value_lab.historical_real_settlement_tape import (
    real_settlement_truth,
)
from strategies.relative_value_lab.historical_reconstruction_input import (
    reconstruction_input_from_case,
)
from strategies.relative_value_lab.historical_feature_reconstruction import (
    feature_from_reconstruction,
)
from strategies.relative_value_lab.historical_phoenix_replay import (
    replay_historical_phoenix,
)


def first_case():
    return HistoricalRealCorpus(
        "data/swarm_data.db"
    ).load_cases()[0]


def test_abstain_has_zero_veto_counterfactual_return():
    case = first_case()

    inp = reconstruction_input_from_case(
        case
    )

    replay = replay_historical_phoenix(
        inp
    )

    fc = next(
        x
        for x in replay.forecasts
        if x.abstain
    )

    out = forecast_outcome_on_real_tape(
        forecast=fc,
        truth=real_settlement_truth(case),
        world_state_id=case.world_state_id,
        world_state_hash=case.world_state_hash,
    )

    assert out.abstain is True
    assert out.realized_net_bps == 0.0


def test_directional_forecast_scores_against_real_tape():
    case = first_case()

    inp = reconstruction_input_from_case(
        case
    )

    replay = replay_historical_phoenix(
        inp
    )

    fc = next(
        x
        for x in replay.forecasts
        if not x.abstain
    )

    truth = real_settlement_truth(
        case
    )

    out = forecast_outcome_on_real_tape(
        forecast=fc,
        truth=truth,
        world_state_id=case.world_state_id,
        world_state_hash=case.world_state_hash,
    )

    sign = (
        1.0
        if fc.direction == "UP"
        else -1.0
    )

    cost = (
        fc.expected_cost_bps
        if fc.expected_cost_bps is not None
        else truth.realized_roundtrip_cost_bps
    )

    expected = (
        sign
        * truth.realized_signed_move_bps
        - cost
    )

    assert abs(
        out.realized_net_bps
        - expected
    ) < 1e-9
