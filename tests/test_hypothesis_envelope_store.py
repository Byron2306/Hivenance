from copy import deepcopy

import pytest

from strategies.relative_value_lab.contracts import (
    ForwardRelativeForecast,
    RELATIVE_VALUE_AUTHORITY,
)
from strategies.relative_value_lab.hypothesis_envelope_assembly import (
    FullOrganismEnvelopeInputs,
    assemble_full_organism_envelope,
)
from strategies.relative_value_lab.hypothesis_envelope_replay import (
    replay_conclusion_bytes,
)
from strategies.relative_value_lab.hypothesis_envelope_store import (
    load_persisted_envelope,
    persist_envelope,
    replay_persisted_conclusion_bytes,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


ROOT = "sha256:" + "a" * 64


def frame():
    obs = ScoreObservation(
        observation_id="o-store",
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
        forecast_id="f-store",
        pair_id="BTC/USD",
        timestamp_ms=1002,
        horizon_seconds=300,
        model_id="model-A",
        expected_relative_move_bps=9.0,
        prediction_lower_bps=1.0,
        prediction_upper_bps=16.0,
        probability_positive_gross=.68,
        expected_cost_bps=4.0,
        expected_net_bps=5.0,
        uncertainty=.25,
        calibration_state="TEST",
        abstain=False,
        reason="store-test",
        feature_digest=ROOT,
        model_lineage={},
        inputs={},
        direction="UP",
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def bound(f, rid):
    return {
        "receipt_id": rid,
        "world_state_id":
            f.world_state_id,
        "world_state_hash":
            f.world_state_hash,
        "execution_eligible": False,
        "promotion_eligible": False,
    }


def inputs(f):
    return FullOrganismEnvelopeInputs(
        canonical_score_frame=f,
        world_state_page=bound(f, "world"),
        temporal_lattice=bound(f, "temporal"),
        evidence_bees=(bound(f, "bee"),),
        comparison_packet=bound(f, "comparison"),
        selection_state=bound(f, "selection"),
        regime=bound(f, "regime"),
        worker_proposals=(bound(f, "worker"),),
        phoenix_hypotheses=(bound(f, "phoenix"),),
        crystal_learning_context=(bound(f, "learning"),),
        quorum=bound(f, "quorum"),
        pollen_state=bound(f, "pollen"),
        triune_scores=bound(f, "triune"),
        queen_receipt=bound(f, "queen"),
        queen_epoch=bound(f, "epoch"),
        recursive_research=bound(f, "recurrence"),
        controls=bound(f, "controls"),
    )


def envelope():
    f = frame()

    return assemble_full_organism_envelope(
        hypothesis_id="h-store",
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


def test_persisted_bytes_equal_canonical_envelope_bytes(tmp_path):
    env = envelope()

    path = persist_envelope(
        root=tmp_path,
        envelope=env,
    )

    assert (
        path.read_bytes()
        == env.canonical_bytes()
    )


def test_round_trip_preserves_envelope_identity(tmp_path):
    env = envelope()

    path = persist_envelope(
        root=tmp_path,
        envelope=env,
    )

    restored = load_persisted_envelope(
        path
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


def test_stored_byte_round_trip_replays_exact_conclusion(tmp_path):
    env = envelope()

    path = persist_envelope(
        root=tmp_path,
        envelope=env,
    )

    assert (
        replay_persisted_conclusion_bytes(
            path
        )
        == replay_conclusion_bytes(env)
    )


def test_store_refuses_overwrite(tmp_path):
    env = envelope()

    persist_envelope(
        root=tmp_path,
        envelope=env,
    )

    with pytest.raises(
        FileExistsError,
        match="already_persisted",
    ):
        persist_envelope(
            root=tmp_path,
            envelope=env,
        )


def test_stored_section_tamper_is_refused(tmp_path):
    env = envelope()

    path = persist_envelope(
        root=tmp_path,
        envelope=env,
    )

    payload = deepcopy(
        env.to_dict()
    )

    payload["sections"]["regime"][
        "tampered"
    ] = True

    import json

    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    with pytest.raises(
        ValueError,
    ):
        load_persisted_envelope(
            path
        )


def test_noncanonical_json_is_refused_even_if_semantically_same(tmp_path):
    env = envelope()

    path = (
        tmp_path
        / f"{env.envelope_id}.json"
    )

    import json

    path.write_text(
        json.dumps(
            env.to_dict(),
            indent=2,
            sort_keys=True,
        )
    )

    with pytest.raises(
        ValueError,
        match="not_canonical",
    ):
        load_persisted_envelope(
            path
        )


def test_external_objects_can_change_after_persist_without_changing_stored_truth(tmp_path):
    f = frame()

    organism = inputs(f)

    env = assemble_full_organism_envelope(
        hypothesis_id="h-store",
        forecast=forecast(),
        inputs=organism,
        world_state_id=f.world_state_id,
        world_state_hash=f.world_state_hash,
        frozen_at_ms=1003,
        influence_ids=(
            "bee",
            "queen",
        ),
    )

    path = persist_envelope(
        root=tmp_path,
        envelope=env,
    )

    before = path.read_bytes()

    organism.regime["later"] = (
        "changed-outside-envelope"
    )

    after = path.read_bytes()

    assert before == after


def test_persisted_envelope_never_gains_authority(tmp_path):
    env = envelope()

    path = persist_envelope(
        root=tmp_path,
        envelope=env,
    )

    restored = load_persisted_envelope(
        path
    )

    assert (
        restored.execution_eligible
        is False
    )

    assert (
        restored.promotion_eligible
        is False
    )

    assert (
        restored.conclusion.execution_eligible
        is False
    )

    assert (
        restored.conclusion.promotion_eligible
        is False
    )
