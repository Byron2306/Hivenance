import pytest

from strategies.relative_value_lab.probabilistic_regime import BayesianRegimeFilter


def roots():
    return ("sha256:" + "a" * 64,)


def test_regime_filter_is_normalized_and_point_in_time():
    filt=BayesianRegimeFilter()
    posterior=filt.update(
        likelihoods={
            "TREND": .8,
            "MEAN_REVERSION": .1,
            "TRANSITION": .08,
            "STRESS": .02,
        },
        as_of_ms=100,
        evidence_available_at_ms=90,
        source_evidence_ids=("market-1",),
        evidence_roots=roots(),
    )
    assert abs(sum(posterior.probabilities.values())-1.0)<1e-6
    assert posterior.dominant_regime=="TREND"
    assert 0.0<=posterior.entropy<=1.0
    assert 0.0<=posterior.change_point_probability<=1.0
    assert posterior.execution_eligible is False
    assert posterior.promotion_eligible is False


def test_regime_filter_detects_transition_pressure():
    filt=BayesianRegimeFilter()
    first=filt.update(
        likelihoods={"TREND": .95, "MEAN_REVERSION": .02, "TRANSITION": .02, "STRESS": .01},
        as_of_ms=100,
        evidence_available_at_ms=90,
        source_evidence_ids=("a",),
        evidence_roots=roots(),
    )
    second=filt.update(
        likelihoods={"TREND": .05, "MEAN_REVERSION": .05, "TRANSITION": .85, "STRESS": .05},
        as_of_ms=200,
        evidence_available_at_ms=190,
        source_evidence_ids=("b",),
        evidence_roots=roots(),
    )
    assert second.previous_posterior_id==first.posterior_id
    assert second.probabilities["TRANSITION"]>first.probabilities["TRANSITION"]
    assert second.change_point_probability>=second.probabilities["TRANSITION"]


def test_regime_filter_rejects_same_time_or_future_evidence():
    filt=BayesianRegimeFilter()
    with pytest.raises(ValueError,match="future_or_same_time"):
        filt.update(
            likelihoods={"TREND": 1.0},
            as_of_ms=100,
            evidence_available_at_ms=100,
            source_evidence_ids=("x",),
            evidence_roots=roots(),
        )
