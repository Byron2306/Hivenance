from strategies.relative_value_lab.research_context import (
    bind_research_context_values,
    build_research_context,
)


def test_research_context_unifies_legacy_organs_without_authority_gain():
    ctx=build_research_context(
        world_state_id="ws1",
        world_state_hash="sha256:"+"a"*64,
        as_of_ms=100,
        feature_values={
            "regime_inputs":{"regime_hint":"trend_expansion","confidence":.7},
            "phase2_learning_feedback":{"support_score":.4},
            "phase2_crystal_memory":{"warning_score":.2},
            "worker_series":{"points":30},
        },
        synthesis_context={"cycle_id":"c1"},
        statistical_state={
            "state_id":"s1",
            "as_of_ms":90,
            "hierarchical_win_probability":.61,
            "hierarchical_edge_positive_probability":.64,
            "uncertainty":.2,
            "change_point_probability":.1,
            "effective_sample_size":12,
        },
        regime_state={
            "posterior_id":"r1",
            "probabilities":{"TREND":.7,"MEAN_REVERSION":.1,"TRANSITION":.15,"STRESS":.05},
        },
        calibration_state={"health_id":"h1","overall_drift_score":.1},
    )
    assert ctx.regime["deterministic"]["regime_hint"]=="trend_expansion"
    assert ctx.regime["bayesian"]["probabilities"]["TREND"]==.7
    assert ctx.statistics["state_id"]=="s1"
    assert ctx.learning["support_score"]==.4
    assert ctx.crystals["warning_score"]==.2
    assert ctx.workers["series"]["points"]==30
    assert ctx.execution_eligible is False
    assert ctx.promotion_eligible is False


def test_research_context_preserves_compatibility_aliases():
    ctx=build_research_context(
        world_state_id="ws1",
        world_state_hash="sha256:"+"a"*64,
        as_of_ms=100,
        feature_values={"regime_inputs":{"regime_hint":"quiet_range"}},
        statistical_state={
            "state_id":"s1",
            "as_of_ms":90,
            "hierarchical_win_probability":.55,
            "hierarchical_edge_positive_probability":.52,
            "uncertainty":.3,
            "change_point_probability":.2,
            "effective_sample_size":6,
        },
    )
    values=bind_research_context_values({},ctx)
    assert values["research_context"]["context_id"]==ctx.context_id
    assert values["regime_inputs"]["regime_hint"]=="quiet_range"
    assert values["phase2_statistical_hypothesis_context"]["state_id"]=="s1"
