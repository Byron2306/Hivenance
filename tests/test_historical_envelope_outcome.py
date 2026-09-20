import pytest

from strategies.relative_value_lab.contracts import (
    ForwardRelativeForecast,
)
from strategies.relative_value_lab.historical_envelope_outcome import (
    HistoricalSettlementTape,
    outcome_from_envelope,
)
from strategies.relative_value_lab.hypothesis_envelope import (
    REQUIRED_SECTIONS,
)
from strategies.relative_value_lab.hypothesis_envelope_assembly import (
    FullOrganismEnvelopeInputs,
    assemble_full_organism_envelope,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


ROOT = "sha256:" + "a" * 64


def frame():
    o = ScoreObservation(
        observation_id="o",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1000,
        evidence_root=ROOT,
        payload={"price": 100},
    )

    return CanonicalWorldScore.assemble(
        observations=(o,),
        assembled_at_ms=1000,
        freshness_window_ms=100,
    )


def env(
    direction,
    *,
    abstain=False,
):
    f = frame()

    forecast = ForwardRelativeForecast(
        schema="rv",
        forecast_id=(
            "f-" + direction
        ),
        pair_id="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=300,
        model_id="m",
        expected_relative_move_bps=10,
        prediction_lower_bps=None,
        prediction_upper_bps=None,
        probability_positive_gross=None,
        expected_cost_bps=2,
        expected_net_bps=8,
        uncertainty=.2,
        calibration_state="TEST",
        abstain=abstain,
        reason="test",
        direction=direction,
    )

    def bound(name):
        return {
            "receipt_id": name,
            "world_state_id":
                f.world_state_id,
            "world_state_hash":
                f.world_state_hash,
            "execution_eligible": False,
            "promotion_eligible": False,
        }

    inputs = FullOrganismEnvelopeInputs(
        canonical_score_frame=f,
        world_state_page=bound("world"),
        temporal_lattice=bound("temporal"),
        evidence_bees=(bound("bee"),),
        comparison_packet=bound("comparison"),
        selection_state={
            **bound("selection"),
            "selected": (
                "BTC/USD",
            ),
        },
        regime=bound("regime"),
        worker_proposals=(bound("worker"),),
        phoenix_hypotheses=(bound("phoenix"),),
        crystal_learning_context=(bound("learning"),),
        quorum=bound("quorum"),
        pollen_state=bound("pollen"),
        triune_scores=bound("triune"),
        queen_receipt=bound("queen"),
        queen_epoch=bound("epoch"),
        recursive_research=bound("recursive"),
        controls=bound("controls"),
    )

    return assemble_full_organism_envelope(
        hypothesis_id="h",
        forecast=forecast,
        inputs=inputs,
        world_state_id=f.world_state_id,
        world_state_hash=f.world_state_hash,
        frozen_at_ms=1001,
        influence_ids=(),
    )


def tape():
    return HistoricalSettlementTape(
        forecast_timestamp_ms=1000,
        horizon_seconds=300,
        settled_timestamp_ms=301000,
        realized_signed_move_bps=10.0,
        expected_cost_bps=2.0,
        source_forecast_id="source",
    )


def test_up_and_down_are_scored_on_same_future_tape():
    up = outcome_from_envelope(
        envelope=env("UP"),
        tape=tape(),
    )

    down = outcome_from_envelope(
        envelope=env("DOWN"),
        tape=tape(),
    )

    assert up.realized_net_bps == 8.0
    assert down.realized_net_bps == -12.0


def test_abstain_has_no_realized_trade_net():
    out = outcome_from_envelope(
        envelope=env(
            "ABSTAIN",
            abstain=True,
        ),
        tape=tape(),
    )

    assert out.abstain is True
    assert out.realized_net_bps is None


def test_selection_state_is_extracted():
    out = outcome_from_envelope(
        envelope=env("UP"),
        tape=tape(),
    )

    assert out.selected is True


def test_wrong_timestamp_refuses():
    bad = HistoricalSettlementTape(
        forecast_timestamp_ms=999,
        horizon_seconds=300,
        settled_timestamp_ms=301000,
        realized_signed_move_bps=10,
        expected_cost_bps=2,
        source_forecast_id="x",
    )

    with pytest.raises(
        ValueError,
        match="timestamp_mismatch",
    ):
        outcome_from_envelope(
            envelope=env("UP"),
            tape=bad,
        )
