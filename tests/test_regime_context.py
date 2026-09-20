import pytest

from strategies.relative_value_lab.regime_context import build_regime_context


def test_regime_context_reconciles_deterministic_and_bayesian_state():
    ctx=build_regime_context(
        as_of_ms=100,
        deterministic={"regime_hint":"trend_expansion","confidence":.8},
        bayesian={
            "schema":"hivenance_regime_posterior_v1",
            "posterior_id":"p1",
            "probabilities":{"TREND":.7,"MEAN_REVERSION":.1,"TRANSITION":.15,"STRESS":.05},
            "dominant_regime":"TREND",
            "entropy":.5,
            "change_point_probability":.2,
            "evidence_available_at_ms":90,
        },
    )
    assert ctx.deterministic_hint=="trend_expansion"
    assert ctx.dominant_posterior_regime=="TREND"
    assert ctx.disagreement_score==.24
    assert ctx.evidence_cutoff_ms==90
    assert ctx.execution_eligible is False


def test_regime_context_surfaces_disagreement():
    ctx=build_regime_context(
        as_of_ms=100,
        deterministic={"regime_hint":"trend_expansion","confidence":1.0},
        bayesian={
            "probabilities":{"TREND":.1,"MEAN_REVERSION":.7,"TRANSITION":.1,"STRESS":.1},
            "dominant_regime":"MEAN_REVERSION",
            "change_point_probability":.3,
            "evidence_available_at_ms":90,
        },
    )
    assert ctx.disagreement_score==.9


def test_regime_context_refuses_same_time_bayesian_evidence():
    with pytest.raises(ValueError,match="future_or_same_time"):
        build_regime_context(
            as_of_ms=100,
            deterministic={"regime_hint":"quiet_range","confidence":.5},
            bayesian={
                "probabilities":{"MEAN_REVERSION":1.0},
                "evidence_available_at_ms":100,
            },
        )
