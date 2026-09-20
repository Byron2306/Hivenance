from strategies.relative_value_lab.learning_influence_gate import (
    evaluate_learning_influence,
)
from strategies.relative_value_lab.learning_retrieval import (
    ApplicabilityLearningBrief,
)


def brief(
    *,
    supported=(),
    contradicted=(),
    regime=(),
    rejected=(),
):
    applicable = tuple(
        supported
        + contradicted
        + regime
    )

    return ApplicabilityLearningBrief(
        applicable_learning_ids=applicable,
        supported_learning_ids=tuple(
            supported
        ),
        contradicted_learning_ids=tuple(
            contradicted
        ),
        regime_dependent_learning_ids=tuple(
            regime
        ),
        rejected_learning_ids=tuple(
            rejected
        ),
        decayed_learning_ids=(),
        superseded_learning_ids=(),
        incomplete_learning_ids=(),
        applicability_decision_ids=(),
        supported_claims=(),
        contradictions=(),
        next_falsifications=(),
        execution_eligible=False,
        promotion_eligible=False,
    )


def test_matching_negative_learning_may_veto():
    decision = evaluate_learning_influence(
        brief=brief(
            contradicted=("negative-1",)
        )
    )

    assert decision.effect == "VETO"
    assert decision.veto is True
    assert decision.challenge is True

    assert (
        decision.contradicting_learning_ids
        == ("negative-1",)
    )

    assert decision.execution_eligible is False
    assert decision.promotion_eligible is False


def test_negative_learning_can_be_challenge_without_veto():
    decision = evaluate_learning_influence(
        brief=brief(
            contradicted=("negative-1",)
        ),
        veto_on_contradiction=False,
    )

    assert decision.effect == "CHALLENGE"
    assert decision.veto is False
    assert decision.challenge is True


def test_positive_learning_is_context_only():
    decision = evaluate_learning_influence(
        brief=brief(
            supported=("positive-1",)
        )
    )

    assert decision.effect == "CONTEXT_ONLY"
    assert decision.veto is False
    assert decision.challenge is False

    assert (
        "positive_learning_context_only"
        in decision.reasons
    )

    assert decision.execution_eligible is False
    assert decision.promotion_eligible is False


def test_regime_dependent_positive_learning_is_context_only():
    decision = evaluate_learning_influence(
        brief=brief(
            regime=("regime-1",)
        )
    )

    assert decision.effect == "CONTEXT_ONLY"
    assert decision.veto is False


def test_rejected_learning_cannot_veto():
    decision = evaluate_learning_influence(
        brief=brief(
            rejected=("wrong-symbol",)
        )
    )

    assert decision.effect == "CONTEXT_ONLY"
    assert decision.veto is False

    assert (
        "wrong-symbol"
        not in decision.contradicting_learning_ids
    )


def test_positive_and_negative_learning_never_create_authority():
    decision = evaluate_learning_influence(
        brief=brief(
            supported=("positive",),
            contradicted=("negative",),
        )
    )

    assert decision.effect == "VETO"

    assert decision.execution_eligible is False
    assert decision.promotion_eligible is False
