from strategies.relative_value_lab.research_context import build_research_context
from strategies.relative_value_lab.research_context_router import (
    allowed_sections,
    project_research_context,
)


def ctx():
    return build_research_context(
        world_state_id="ws1",
        world_state_hash="sha256:"+"a"*64,
        as_of_ms=100,
        feature_values={
            "regime_inputs":{"regime_hint":"trend_expansion","confidence":.7},
            "phase2_learning_feedback":{"support_score":.4},
            "phase2_crystal_memory":{"warning_score":.1},
            "worker_series":{"points":20},
        },
        statistical_state={
            "state_id":"s1",
            "as_of_ms":90,
            "hierarchical_win_probability":.6,
            "uncertainty":.2,
            "change_point_probability":.1,
            "effective_sample_size":10,
        },
        calibration_state={"health_id":"h1"},
    )


def test_workers_do_not_receive_external_or_provenance_by_default():
    view=project_research_context(ctx(),organ_id="strategy_workers")
    assert "regime" in view.sections
    assert "statistics" in view.sections
    assert "learning" in view.sections
    assert "external" not in view.sections
    assert "provenance" not in view.sections
    assert view.execution_eligible is False


def test_pollen_is_meta_learning_not_market_observer():
    view=project_research_context(ctx(),organ_id="pollen_economy")
    assert set(view.allowed_sections)=={"learning","calibration","workers","provenance"}
    assert "observed" not in view.sections
    assert "regime" not in view.sections


def test_queen_receives_broadest_governed_context():
    allowed=set(allowed_sections("conducting_queen"))
    assert {
        "observed","regime","statistics","learning","crystals",
        "external","calibration","workers","provenance",
    }==allowed
