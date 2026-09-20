import pytest

from strategies.relative_value_lab.hypothesis_envelope import (
    REQUIRED_SECTIONS,
    HypothesisConclusion,
    build_hypothesis_envelope,
    verify_hypothesis_envelope,
)


WH = "sha256:" + "f" * 64


def sections():
    return {
        name: {
            "section": name,
            "receipt_id": "r-" + name,
        }
        for name in REQUIRED_SECTIONS
    }


def conclusion(
    *,
    influences=("bee-flow", "queen-1"),
):
    return HypothesisConclusion(
        hypothesis_id="h1",
        forecast_id="f1",
        symbol="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=300,
        direction="UP",
        abstain=False,
        expected_move_bps=10.0,
        expected_cost_bps=4.0,
        expected_net_bps=6.0,
        uncertainty=.2,
        influence_ids=tuple(influences),
    )


def build(
    *,
    section_values=None,
    influences=("bee-flow", "queen-1"),
    result=None,
):
    return build_hypothesis_envelope(
        hypothesis_id="h1",
        forecast_id="f1",
        world_state_id="world-1",
        world_state_hash=WH,
        frozen_at_ms=1000,
        sections=(
            section_values
            or sections()
        ),
        declared_influence_ids=(
            influences
        ),
        conclusion=(
            result
            or conclusion(
                influences=influences
            )
        ),
    )


def test_same_inputs_produce_same_envelope_id_and_bytes():
    a = build()
    b = build()

    assert a == b
    assert a.envelope_id == b.envelope_id

    assert (
        a.canonical_bytes()
        == b.canonical_bytes()
    )

    assert verify_hypothesis_envelope(a)


def test_every_master_plan_section_is_required():
    values = sections()

    del values["queen_receipt"]

    with pytest.raises(
        ValueError,
        match="missing_sections",
    ):
        build(
            section_values=values
        )


def test_unknown_section_is_refused():
    values = sections()
    values["secret_feature"] = {
        "value": 123
    }

    with pytest.raises(
        ValueError,
        match="unknown_sections",
    ):
        build(
            section_values=values
        )


def test_undeclared_influence_is_refused():
    result = conclusion(
        influences=(
            "bee-flow",
            "queen-1",
            "secret-model",
        )
    )

    with pytest.raises(
        ValueError,
        match="undeclared_influence",
    ):
        build(
            influences=(
                "bee-flow",
                "queen-1",
            ),
            result=result,
        )


def test_declared_but_unused_influence_is_also_refused():
    result = conclusion(
        influences=(
            "bee-flow",
        )
    )

    with pytest.raises(
        ValueError,
        match="undeclared_influence",
    ):
        build(
            influences=(
                "bee-flow",
                "queen-1",
            ),
            result=result,
        )


def test_changing_one_section_changes_envelope_identity():
    first = build()

    changed = sections()

    changed["regime"] = {
        "section": "regime",
        "receipt_id": "regime-new",
    }

    second = build(
        section_values=changed
    )

    assert (
        first.envelope_id
        != second.envelope_id
    )

    assert (
        first.section_digests["regime"]
        != second.section_digests["regime"]
    )


def test_section_key_order_does_not_change_identity():
    original = sections()

    reversed_sections = dict(
        reversed(
            list(original.items())
        )
    )

    first = build(
        section_values=original
    )

    second = build(
        section_values=reversed_sections
    )

    assert first.envelope_id == second.envelope_id
    assert (
        first.canonical_bytes()
        == second.canonical_bytes()
    )


def test_abstaining_conclusion_must_be_explicit():
    result = HypothesisConclusion(
        hypothesis_id="h1",
        forecast_id="f1",
        symbol="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=300,
        direction="ABSTAIN",
        abstain=True,
        expected_move_bps=None,
        expected_cost_bps=4.0,
        expected_net_bps=None,
        uncertainty=.8,
        influence_ids=("queen-1",),
    )

    envelope = build(
        influences=("queen-1",),
        result=result,
    )

    assert envelope.conclusion.abstain is True
    assert (
        envelope.conclusion.direction
        == "ABSTAIN"
    )


def test_envelope_cannot_gain_execution_or_promotion():
    envelope = build()

    assert envelope.execution_eligible is False
    assert envelope.promotion_eligible is False

    assert (
        envelope.conclusion.execution_eligible
        is False
    )

    assert (
        envelope.conclusion.promotion_eligible
        is False
    )


def test_nested_mutation_changes_digest_not_existing_envelope():
    values = sections()

    envelope = build(
        section_values=values
    )

    old_id = envelope.envelope_id

    values["controls"]["new"] = "mutation"

    # Existing envelope contains its frozen canonical copy.
    assert envelope.envelope_id == old_id

    rebuilt = build(
        section_values=values
    )

    assert rebuilt.envelope_id != old_id
