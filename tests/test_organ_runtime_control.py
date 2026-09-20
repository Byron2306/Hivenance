from strategies.relative_value_lab.organ_runtime_control import (
    build_runtime_control_plane,
    resolve_runtime_state,
)


def test_harmful_or_mixed_is_quarantined_but_still_shadow_probed():
    row = resolve_runtime_state(
        organ_id="strategy_workers",
        utility_state="HISTORICALLY_MIXED",
    )
    assert row.mode == "QUARANTINED"
    assert row.influence_enabled is False
    assert row.shadow_probe_enabled is True


def test_inert_non_governance_organ_is_dormant_not_deleted():
    row = resolve_runtime_state(
        organ_id="bayesian_regime_filter",
        utility_state="INERT_ON_TESTED_WORLDS",
    )
    assert row.mode == "DORMANT"
    assert row.shadow_probe_enabled is True


def test_active_request_degrades_to_shadow_without_prospective_depth():
    row = resolve_runtime_state(
        organ_id="statistics_bee",
        utility_state="HISTORICALLY_USEFUL",
        requested_mode="ACTIVE",
        prospective_worlds=5,
        prospective_positive_worlds=5,
        prospective_negative_worlds=0,
        minimum_prospective_worlds_for_active=20,
    )
    assert row.mode == "SHADOW"
    assert row.influence_enabled is False


def test_active_request_can_be_earned_and_is_reversible():
    active = resolve_runtime_state(
        organ_id="statistics_bee",
        utility_state="HISTORICALLY_USEFUL",
        requested_mode="ACTIVE",
        prospective_worlds=25,
        prospective_positive_worlds=25,
        prospective_negative_worlds=0,
        minimum_prospective_worlds_for_active=20,
    )
    assert active.mode == "ACTIVE"
    assert active.influence_enabled is True
    assert active.execution_eligible is False

    shadow = resolve_runtime_state(
        organ_id="statistics_bee",
        utility_state="HISTORICALLY_USEFUL",
        requested_mode="SHADOW",
        prospective_worlds=25,
        prospective_positive_worlds=25,
        prospective_negative_worlds=0,
    )
    assert shadow.mode == "SHADOW"
    assert shadow.influence_enabled is False


def test_control_plane_accepts_runtime_requests_without_hard_deletion():
    rows = [
        {
            "organ_id":"learning_memory",
            "utility_state":"INERT_ON_TESTED_WORLDS",
            "historical_paired_delta_bps":None,
            "dependence_adjusted_world_count":0,
        },
        {
            "organ_id":"statistics_bee",
            "utility_state":"HISTORICALLY_USEFUL",
            "historical_paired_delta_bps":44.2,
            "dependence_adjusted_world_count":9,
        },
    ]
    plane = build_runtime_control_plane(
        rows,
        requested_modes={
            "learning_memory":"SHADOW",
            "statistics_bee":"ACTIVE",
        },
        prospective_evidence={
            "statistics_bee":{
                "worlds":30,
                "positive_worlds":30,
                "negative_worlds":0,
            }
        },
    )
    assert plane["learning_memory"].mode == "SHADOW"
    assert plane["statistics_bee"].mode == "ACTIVE"
