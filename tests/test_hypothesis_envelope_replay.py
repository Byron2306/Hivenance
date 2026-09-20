from copy import deepcopy

import pytest

from strategies.relative_value_lab.contracts import (
    ForwardRelativeForecast,
    RELATIVE_VALUE_AUTHORITY,
)
from strategies.relative_value_lab.hypothesis_envelope import (
    HypothesisConclusion,
)
from strategies.relative_value_lab.hypothesis_envelope_assembly import (
    FullOrganismEnvelopeInputs,
    assemble_full_organism_envelope,
)
from strategies.relative_value_lab.hypothesis_envelope_replay import (
    envelope_from_dict,
    replay_conclusion,
    replay_conclusion_bytes,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


ROOT = "sha256:" + "a" * 64


def frame():
    obs = ScoreObservation(
        observation_id="o",
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
        schema="hivenance_forward_relative_forecast_v1",
        forecast_id="f-replay",
        pair_id="BTC/USD",
        timestamp_ms=1002,
        horizon_seconds=300,
        model_id="model-A",
        expected_relative_move_bps=12.0,
        prediction_lower_bps=3.0,
        prediction_upper_bps=20.0,
        probability_positive_gross=.72,
        expected_cost_bps=4.0,
        expected_net_bps=8.0,
        uncertainty=.18,
        calibration_state="TEST",
        abstain=False,
        reason="replay-test",
        feature_digest=ROOT,
        model_lineage={},
        inputs={},
        direction="UP",
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def bound(f, rid, **extra):
    return {
        "receipt_id": rid,
        "world_state_id":
            f.world_state_id,
        "world_state_hash":
            f.world_state_hash,
        "execution_eligible": False,
        "promotion_eligible": False,
        **extra,
    }


def inputs(f):
    return FullOrganismEnvelopeInputs(
        canonical_score_frame=f,
        world_state_page=bound(
            f,
            "world",
        ),
        temporal_lattice=bound(
            f,
            "temporal",
        ),
        evidence_bees=(
            bound(
                f,
                "bee",
                family="FLOW",
            ),
        ),
        comparison_packet=bound(
            f,
            "comparison",
        ),
        selection_state=bound(
            f,
            "selection",
        ),
        regime=bound(
            f,
            "regime",
        ),
        worker_proposals=(
            bound(
                f,
                "worker",
            ),
        ),
        phoenix_hypotheses=(
            bound(
                f,
                "phoenix",
            ),
        ),
        crystal_learning_context=(
            bound(
                f,
                "learning",
            ),
        ),
        quorum=bound(
            f,
            "quorum",
        ),
        pollen_state=bound(
            f,
            "pollen",
        ),
        triune_scores=bound(
            f,
            "triune",
        ),
        queen_receipt=bound(
            f,
            "queen",
        ),
        queen_epoch=bound(
            f,
            "epoch",
        ),
        recursive_research=bound(
            f,
            "recurrence",
        ),
        controls=bound(
            f,
            "controls",
        ),
    )


def envelope():
    f = frame()

    return assemble_full_organism_envelope(
        hypothesis_id="h-replay",
        forecast=forecast(),
        inputs=inputs(f),
        world_state_id=f.world_state_id,
        world_state_hash=f.world_state_hash,
        frozen_at_ms=1003,
        influence_ids=(
            "bee",
            "queen",
        ),
    )


def test_replay_reproduces_frozen_conclusion_exactly():
    env = envelope()

    replayed = replay_conclusion(
        env
    )

    assert replayed == env.conclusion

    assert (
        replay_conclusion_bytes(env)
        == replay_conclusion_bytes(env)
    )


def test_serialized_envelope_reloads_to_same_identity():
    env = envelope()

    restored = envelope_from_dict(
        env.to_dict()
    )

    assert restored.envelope_id == (
        env.envelope_id
    )

    assert (
        restored.canonical_payload_digest
        == env.canonical_payload_digest
    )

    assert (
        restored.canonical_bytes()
        == env.canonical_bytes()
    )

    assert (
        replay_conclusion_bytes(restored)
        == replay_conclusion_bytes(env)
    )


def test_external_object_mutation_after_freeze_cannot_change_replay():
    f = frame()

    original_inputs = inputs(f)

    env = assemble_full_organism_envelope(
        hypothesis_id="h-replay",
        forecast=forecast(),
        inputs=original_inputs,
        world_state_id=f.world_state_id,
        world_state_hash=f.world_state_hash,
        frozen_at_ms=1003,
        influence_ids=(
            "bee",
            "queen",
        ),
    )

    before = replay_conclusion_bytes(
        env
    )

    original_inputs.regime["regime"] = (
        "POST_FREEZE_MUTATION"
    )

    after = replay_conclusion_bytes(
        env
    )

    assert before == after


def test_section_tamper_is_detected_on_reload():
    env = envelope()

    payload = deepcopy(
        env.to_dict()
    )

    payload["sections"]["regime"][
        "regime"
    ] = "TAMPERED"

    with pytest.raises(
        ValueError,
    ):
        envelope_from_dict(
            payload
        )


def test_conclusion_tamper_is_detected_on_reload():
    env = envelope()

    payload = deepcopy(
        env.to_dict()
    )

    payload["conclusion"][
        "direction"
    ] = "DOWN"

    with pytest.raises(
        ValueError,
    ):
        envelope_from_dict(
            payload
        )


def test_influence_tamper_is_detected():
    env = envelope()

    payload = deepcopy(
        env.to_dict()
    )

    payload[
        "declared_influence_ids"
    ] = (
        "bee",
        "queen",
        "secret-model",
    )

    with pytest.raises(
        ValueError,
    ):
        envelope_from_dict(
            payload
        )


def test_replay_cannot_gain_execution_or_promotion():
    env = envelope()

    replayed = replay_conclusion(
        env
    )

    assert (
        replayed.execution_eligible
        is False
    )

    assert (
        replayed.promotion_eligible
        is False
    )
