import pytest

from strategies.relative_value_lab.historical_mask_engine import (
    historical_mask_plan,
)
from strategies.relative_value_lab.historical_upper_cognition_mask_bridge import (
    prepare_upper_cognition_replay,
    run_upper_cognition_replay,
)


class Sentinel:
    def __init__(self, name):
        self.name = name


def kwargs():
    return {
        "hypothesis_id": "h1",
        "notes": (),
        "motif": Sentinel("motif"),
        "entrainment": Sentinel("entrainment"),
        "epoch": Sentinel("epoch"),
        "vns_pulses": (),
        "vns_phrase": Sentinel("vns_phrase"),
        "harmonic_context": {},
        "temporal_texture":
            Sentinel("temporal_texture"),
        "edge_chorus": None,
        "hunt_matches": (),
        "correlations": (),
        "cascade": None,
        "hive_pulses": (),
        "polyphonic_resonance":
            Sentinel("resonance"),
        "mystique": Sentinel("mystique"),
        "metabolism":
            Sentinel("metabolism"),
        "learned_challengers": (),
        "now_ms": 1000,
        "world_state_id": "world-1",
        "world_state_hash":
            "sha256:" + "a" * 64,
    }


def test_full_hive_preserves_upper_inputs():
    original = kwargs()

    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "FULL_HIVE"
        ),
        queen_kwargs=original,
    )

    assert state.invoke_queen is True
    assert state.quorum_enabled is True
    assert state.pollen_enabled is True

    assert (
        state.queen_kwargs["vns_phrase"]
        is original["vns_phrase"]
    )

    assert (
        state.queen_kwargs[
            "temporal_texture"
        ]
        is original["temporal_texture"]
    )


def test_no_vns_phrase_removes_phrase_before_queen():
    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_VNS_PHRASE"
        ),
        queen_kwargs=kwargs(),
    )

    assert (
        state.queen_kwargs["vns_phrase"]
        is None
    )

    assert state.invoke_queen is True


def test_no_temporal_texture_removes_texture_before_queen():
    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_TEMPORAL_TEXTURE"
        ),
        queen_kwargs=kwargs(),
    )

    assert (
        state.queen_kwargs[
            "temporal_texture"
        ]
        is None
    )


def test_no_mystique_removes_challenge_before_queen():
    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_MYSTIQUE"
        ),
        queen_kwargs=kwargs(),
    )

    assert (
        state.queen_kwargs["mystique"]
        is None
    )


def test_no_metabolism_removes_metabolism_before_queen():
    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_METABOLISM"
        ),
        queen_kwargs=kwargs(),
    )

    assert (
        state.queen_kwargs["metabolism"]
        is None
    )


def test_no_quorum_removes_resonance_and_disables_quorum():
    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_QUORUM"
        ),
        queen_kwargs=kwargs(),
    )

    assert state.quorum_enabled is False

    assert (
        state.queen_kwargs[
            "polyphonic_resonance"
        ]
        is None
    )

    assert state.invoke_queen is True


def test_no_pollen_disables_pollen_but_not_queen():
    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_POLLEN"
        ),
        queen_kwargs=kwargs(),
    )

    assert state.pollen_enabled is False
    assert state.invoke_queen is True


def test_no_queen_does_not_invoke_queen_at_all():
    calls = []

    def runner(**kw):
        calls.append(kw)
        return "SHOULD_NOT_EXIST"

    result = run_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_QUEEN"
        ),
        queen_kwargs=kwargs(),
        queen_runner=runner,
    )

    assert result.queen_invoked is False
    assert result.queen_receipt is None
    assert calls == []


def test_normal_upper_mask_invokes_runner_with_filtered_inputs():
    calls = []

    def runner(**kw):
        calls.append(kw)
        return {
            "receipt_id": "queen-masked"
        }

    result = run_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_MYSTIQUE"
        ),
        queen_kwargs=kwargs(),
        queen_runner=runner,
    )

    assert result.queen_invoked is True

    assert len(calls) == 1

    assert calls[0]["mystique"] is None

    assert result.queen_receipt == {
        "receipt_id": "queen-masked"
    }


def test_unrelated_upper_input_is_not_changed_by_single_mask():
    original = kwargs()

    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_VNS_PHRASE"
        ),
        queen_kwargs=original,
    )

    assert (
        state.queen_kwargs[
            "temporal_texture"
        ]
        is original["temporal_texture"]
    )

    assert (
        state.queen_kwargs["mystique"]
        is original["mystique"]
    )

    assert (
        state.queen_kwargs["metabolism"]
        is original["metabolism"]
    )


def test_lower_spine_mask_refuses_at_upper_bridge():
    with pytest.raises(
        ValueError,
        match="not_executable",
    ):
        prepare_upper_cognition_replay(
            mask=historical_mask_plan(
                "NO_FLOW"
            ),
            queen_kwargs=kwargs(),
        )


def test_upper_bridge_never_grants_authority():
    state = prepare_upper_cognition_replay(
        mask=historical_mask_plan(
            "NO_POLLEN"
        ),
        queen_kwargs=kwargs(),
    )

    assert state.execution_eligible is False
    assert state.promotion_eligible is False
