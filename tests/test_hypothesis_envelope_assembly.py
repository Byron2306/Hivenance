import pytest

from strategies.relative_value_lab.contracts import (
    ForwardRelativeForecast,
    RELATIVE_VALUE_AUTHORITY,
)
from strategies.relative_value_lab.hypothesis_envelope import (
    verify_hypothesis_envelope,
)
from strategies.relative_value_lab.hypothesis_envelope_assembly import (
    FullOrganismEnvelopeInputs,
    assemble_full_organism_envelope,
    conclusion_from_forecast,
)
from strategies.relative_value_lab.world_graph import (
    WorldGraph,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


ROOT = "sha256:" + "a" * 64


def frame():
    obs = ScoreObservation(
        observation_id="obs-envelope",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1001,
        evidence_root=ROOT,
        payload={"price": 100.0},
    )

    return CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=1002,
        freshness_window_ms=10000,
    )


def forecast():
    return ForwardRelativeForecast(
        schema=(
            "hivenance_forward_relative_forecast_v1"
        ),
        forecast_id="forecast-envelope",
        pair_id="BTC/USD",
        timestamp_ms=1002,
        horizon_seconds=300,
        model_id="model-A",
        expected_relative_move_bps=10.0,
        prediction_lower_bps=2.0,
        prediction_upper_bps=18.0,
        probability_positive_gross=.7,
        expected_cost_bps=4.0,
        expected_net_bps=6.0,
        uncertainty=.2,
        calibration_state="TEST",
        abstain=False,
        reason="test-envelope",
        feature_digest=ROOT,
        model_lineage={
            "model": "model-A",
        },
        inputs={},
        direction="UP",
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def bound(
    f,
    *,
    name,
    **extra,
):
    return {
        "receipt_id": name,
        "world_state_id":
            f.world_state_id,
        "world_state_hash":
            f.world_state_hash,
        "execution_eligible": False,
        "promotion_eligible": False,
        **extra,
    }


def organism_inputs(f):
    graph = WorldGraph(f)

    queen_view = graph.queen_view(
        created_at_ms=1003
    )

    return FullOrganismEnvelopeInputs(
        canonical_score_frame=f,

        world_state_page=bound(
            f,
            name="world-page",
        ),

        temporal_lattice=bound(
            f,
            name="temporal-lattice",
            horizons={
                "5m": "AVAILABLE",
                "1h": "AVAILABLE",
            },
        ),

        evidence_bees=(
            bound(
                f,
                name="bee-flow",
                family="FLOW",
                evidence_root=ROOT,
            ),
        ),

        comparison_packet=bound(
            f,
            name="comparison-packet",
        ),

        selection_state=bound(
            f,
            name="selection-state",
            selected=("BTC/USD",),
            rejected=("ETH/USD",),
        ),

        regime=bound(
            f,
            name="regime",
            regime="TREND",
        ),

        worker_proposals=(
            bound(
                f,
                name="worker-1",
            ),
        ),

        phoenix_hypotheses=(
            bound(
                f,
                name="phoenix-hypothesis",
            ),
        ),

        crystal_learning_context=(
            bound(
                f,
                name="learning-1",
                state="SUPPORTED",
            ),
        ),

        quorum=bound(
            f,
            name="quorum-1",
            quorum_formed=True,
        ),

        pollen_state=bound(
            f,
            name="pollen-1",
        ),

        triune_scores=bound(
            f,
            name="triune-1",
        ),

        # Real WorldGraph QueenView object.
        queen_receipt=queen_view,

        queen_epoch=bound(
            f,
            name="epoch-1",
            epoch=1,
        ),

        recursive_research=bound(
            f,
            name="recursive-run",
            steps=(),
        ),

        controls=bound(
            f,
            name="controls",
            declared=(
                "NO_TRADE",
                "DETERMINISTIC_RANDOM",
            ),
        ),
    )


def test_forecast_is_frozen_not_recomputed():
    c = conclusion_from_forecast(
        hypothesis_id="h-envelope",
        forecast=forecast(),
        influence_ids=(
            "bee-flow",
            "queen-1",
        ),
    )

    assert c.direction == "UP"
    assert c.abstain is False

    assert c.expected_move_bps == 10.0
    assert c.expected_cost_bps == 4.0
    assert c.expected_net_bps == 6.0

    assert c.execution_eligible is False
    assert c.promotion_eligible is False


def test_full_organism_can_be_frozen_into_one_envelope():
    f = frame()

    envelope = assemble_full_organism_envelope(
        hypothesis_id="h-envelope",
        forecast=forecast(),
        inputs=organism_inputs(f),
        world_state_id=f.world_state_id,
        world_state_hash=f.world_state_hash,
        frozen_at_ms=1004,
        influence_ids=(
            "bee-flow",
            "queen-1",
        ),
    )

    assert verify_hypothesis_envelope(
        envelope
    )

    assert (
        envelope.world_state_id
        == f.world_state_id
    )

    assert (
        envelope.world_state_hash
        == f.world_state_hash
    )

    assert (
        len(envelope.sections)
        == 17
    )

    assert (
        envelope.conclusion.direction
        == "UP"
    )


def test_cross_world_nested_receipt_is_refused():
    f = frame()

    inputs = organism_inputs(f)

    bad = FullOrganismEnvelopeInputs(
        **{
            **inputs.__dict__,
            "regime": {
                "receipt_id": "bad-regime",
                "world_state_id":
                    "different-world",
                "world_state_hash":
                    f.world_state_hash,
                "execution_eligible":
                    False,
                "promotion_eligible":
                    False,
            },
        }
    )

    with pytest.raises(
        ValueError,
        match="cross_world_id",
    ):
        assemble_full_organism_envelope(
            hypothesis_id="h-envelope",
            forecast=forecast(),
            inputs=bad,
            world_state_id=(
                f.world_state_id
            ),
            world_state_hash=(
                f.world_state_hash
            ),
            frozen_at_ms=1004,
            influence_ids=(
                "bee-flow",
                "queen-1",
            ),
        )


def test_cross_world_hash_is_refused():
    f = frame()

    inputs = organism_inputs(f)

    bad = FullOrganismEnvelopeInputs(
        **{
            **inputs.__dict__,
            "quorum": {
                "receipt_id": "bad-quorum",
                "world_state_id":
                    f.world_state_id,
                "world_state_hash":
                    "sha256:" + "b" * 64,
                "execution_eligible":
                    False,
                "promotion_eligible":
                    False,
            },
        }
    )

    with pytest.raises(
        ValueError,
        match="cross_world_hash",
    ):
        assemble_full_organism_envelope(
            hypothesis_id="h-envelope",
            forecast=forecast(),
            inputs=bad,
            world_state_id=(
                f.world_state_id
            ),
            world_state_hash=(
                f.world_state_hash
            ),
            frozen_at_ms=1004,
            influence_ids=(),
        )


def test_nested_execution_authority_is_refused():
    f = frame()

    inputs = organism_inputs(f)

    bad = FullOrganismEnvelopeInputs(
        **{
            **inputs.__dict__,
            "worker_proposals": (
                {
                    "receipt_id":
                        "rogue-worker",
                    "world_state_id":
                        f.world_state_id,
                    "world_state_hash":
                        f.world_state_hash,
                    "execution_eligible":
                        True,
                },
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="execution_authority_found",
    ):
        assemble_full_organism_envelope(
            hypothesis_id="h-envelope",
            forecast=forecast(),
            inputs=bad,
            world_state_id=(
                f.world_state_id
            ),
            world_state_hash=(
                f.world_state_hash
            ),
            frozen_at_ms=1004,
            influence_ids=(),
        )


def test_nested_promotion_authority_is_refused():
    f = frame()

    inputs = organism_inputs(f)

    bad = FullOrganismEnvelopeInputs(
        **{
            **inputs.__dict__,
            "crystal_learning_context": (
                {
                    "receipt_id":
                        "rogue-learning",
                    "world_state_id":
                        f.world_state_id,
                    "world_state_hash":
                        f.world_state_hash,
                    "execution_eligible":
                        False,
                    "promotion_eligible":
                        True,
                },
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="promotion_authority_found",
    ):
        assemble_full_organism_envelope(
            hypothesis_id="h-envelope",
            forecast=forecast(),
            inputs=bad,
            world_state_id=(
                f.world_state_id
            ),
            world_state_hash=(
                f.world_state_hash
            ),
            frozen_at_ms=1004,
            influence_ids=(),
        )


def test_same_full_organism_produces_identical_envelope():
    f = frame()

    kwargs = dict(
        hypothesis_id="h-envelope",
        forecast=forecast(),
        inputs=organism_inputs(f),
        world_state_id=f.world_state_id,
        world_state_hash=f.world_state_hash,
        frozen_at_ms=1004,
        influence_ids=(
            "bee-flow",
            "queen-1",
        ),
    )

    a = assemble_full_organism_envelope(
        **kwargs
    )

    b = assemble_full_organism_envelope(
        **kwargs
    )

    assert a.envelope_id == b.envelope_id

    assert (
        a.canonical_bytes()
        == b.canonical_bytes()
    )
