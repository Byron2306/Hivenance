from strategies.relative_value_lab.learning_decision_adapter import (
    apply_learning_influence,
)
from strategies.relative_value_lab.learning_influence_gate import (
    LearningInfluenceDecision,
)


def influence(
    *,
    effect,
    veto,
    challenge,
):
    return LearningInfluenceDecision(
        schema=(
            "hivenance_learning_influence_decision_v1"
        ),
        decision_id="learning-decision",
        effect=effect,
        veto=veto,
        challenge=challenge,
        applicable_learning_ids=(),
        supporting_learning_ids=(),
        contradicting_learning_ids=(),
        reasons=(),
    )


def test_negative_learning_can_force_abstention():
    out = apply_learning_influence(
        direction="UP",
        abstain=False,
        learning=influence(
            effect="VETO",
            veto=True,
            challenge=True,
        ),
    )

    assert out.original_direction == "UP"
    assert out.final_direction == "ABSTAIN"
    assert out.final_abstain is True


def test_positive_learning_cannot_create_direction_from_abstain():
    out = apply_learning_influence(
        direction="UP",
        abstain=True,
        learning=influence(
            effect="CONTEXT_ONLY",
            veto=False,
            challenge=False,
        ),
    )

    assert out.final_direction == "ABSTAIN"
    assert out.final_abstain is True


def test_positive_learning_cannot_flip_direction():
    out = apply_learning_influence(
        direction="DOWN",
        abstain=False,
        learning=influence(
            effect="CONTEXT_ONLY",
            veto=False,
            challenge=False,
        ),
    )

    assert out.final_direction == "DOWN"
    assert out.final_abstain is False


def test_challenge_without_veto_preserves_current_decision():
    out = apply_learning_influence(
        direction="UP",
        abstain=False,
        learning=influence(
            effect="CHALLENGE",
            veto=False,
            challenge=True,
        ),
    )

    assert out.final_direction == "UP"
    assert out.final_abstain is False


def test_learning_adapter_never_grants_execution_or_promotion():
    out = apply_learning_influence(
        direction="UP",
        abstain=False,
        learning=influence(
            effect="CONTEXT_ONLY",
            veto=False,
            challenge=False,
        ),
    )

    assert out.execution_eligible is False
    assert out.promotion_eligible is False
