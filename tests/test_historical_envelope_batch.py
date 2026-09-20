from pathlib import Path

from strategies.relative_value_lab.contracts import (
    ForwardRelativeForecast,
)
from strategies.relative_value_lab.historical_envelope_batch import (
    HistoricalEnvelopePairInput,
    prosecute_envelope_batch,
)
from strategies.relative_value_lab.historical_envelope_outcome import (
    HistoricalSettlementTape,
)
from strategies.relative_value_lab.hypothesis_envelope_assembly import (
    FullOrganismEnvelopeInputs,
    assemble_full_organism_envelope,
)
from strategies.relative_value_lab.hypothesis_envelope_store import (
    persist_envelope,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


def make_env(
    *,
    i,
    direction,
):
    root = (
        "sha256:"
        + format(
            i + 1,
            "064x",
        )
    )

    obs = ScoreObservation(
        observation_id=f"o{i}",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000 + i,
        received_at_ms=1000 + i,
        evidence_root=root,
        payload={"price": 100 + i},
    )

    frame = CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=1000 + i,
        freshness_window_ms=100,
    )

    forecast = ForwardRelativeForecast(
        schema="rv",
        forecast_id=f"f-{direction}-{i}",
        pair_id="BTC/USD",
        timestamp_ms=1000 + i,
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
        abstain=False,
        reason="test",
        direction=direction,
    )

    def bound(name):
        return {
            "receipt_id":
                f"{name}-{i}",
            "world_state_id":
                frame.world_state_id,
            "world_state_hash":
                frame.world_state_hash,
            "execution_eligible":
                False,
            "promotion_eligible":
                False,
        }

    inputs = FullOrganismEnvelopeInputs(
        canonical_score_frame=frame,
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
        world_state_id=frame.world_state_id,
        world_state_hash=frame.world_state_hash,
        frozen_at_ms=2000 + i,
        influence_ids=(),
    )


def test_stored_envelope_batch_produces_historical_organ_result(
    tmp_path,
):
    cases = []

    for i in range(6):
        full = make_env(
            i=i,
            direction="UP",
        )

        masked = make_env(
            i=i,
            direction="DOWN",
        )

        full_dir = (
            tmp_path
            / "full"
        )

        masked_dir = (
            tmp_path
            / "masked"
        )

        fp = persist_envelope(
            root=full_dir,
            envelope=full,
        )

        mp = persist_envelope(
            root=masked_dir,
            envelope=masked,
        )

        cases.append(
            HistoricalEnvelopePairInput(
                full_envelope_path=fp,
                masked_envelope_path=mp,
                settlement_tape=(
                    HistoricalSettlementTape(
                        forecast_timestamp_ms=(
                            1000 + i
                        ),
                        horizon_seconds=300,
                        settled_timestamp_ms=(
                            301000 + i
                        ),
                        realized_signed_move_bps=10.0,
                        expected_cost_bps=2.0,
                        source_forecast_id=(
                            f"source-{i}"
                        ),
                    )
                ),
                dependence_cluster_id=(
                    f"cluster-{i // 2}"
                ),
            )
        )

    result = prosecute_envelope_batch(
        organ_id="FLOW",
        mask_id="NO_FLOW",
        cases=cases,
        available=True,
        invoked_count=6,
        non_default_output_count=6,
        minimum_paired_worlds=5,
    )

    assert len(result.pairs) == 6

    assert (
        result.prosecution.decision_change_count
        == 6
    )

    assert (
        result.prosecution.direction_change_count
        == 6
    )

    # UP: +10 - 2 = +8
    # DOWN: -10 - 2 = -12
    assert (
        result.prosecution.historical_paired_delta_bps
        == 20.0
    )

    assert (
        result.prosecution.classification
        == "HISTORICALLY_USEFUL"
    )

    assert (
        result.prosecution.dependence_adjusted_world_count
        == 3
    )

    assert result.execution_eligible is False
    assert result.promotion_eligible is False
