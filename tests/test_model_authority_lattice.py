from strategies.relative_value_lab.model_authority_lattice import (
    model_authority_manifest,
    resolve_model_authority,
)


def resolve(rules, *, model="worker_signal_rsi_v1", horizon=3600, regime="quiet_range", cohort="mean_reversion"):
    return resolve_model_authority(
        model_id=model,
        horizon_seconds=horizon,
        regime=regime,
        cohort_bucket=cohort,
        rules=rules,
    )


def test_no_rule_falls_back_without_granting_authority():
    decision = resolve(())
    assert decision.matched is False
    assert decision.mode is None
    assert decision.influence_enabled is False
    assert decision.source == "coarse_organ_authority_fallback"
    assert decision.to_dict()["execution_eligible"] is False
    assert decision.to_dict()["promotion_eligible"] is False


def test_horizon_specific_rule_beats_model_only_rule():
    rules = (
        {"model_id": "worker_signal_rsi_v1", "mode": "SHADOW"},
        {
            "model_id": "worker_signal_rsi_v1",
            "horizon_seconds": 3600,
            "mode": "ACTIVE",
            "source": "prospective_replication_freeze",
        },
    )
    decision = resolve(rules)
    assert decision.matched is True
    assert decision.mode == "ACTIVE"
    assert decision.influence_enabled is True
    assert decision.specificity == 2
    assert decision.matched_rule_index == 1


def test_regime_and_cohort_can_narrow_same_model_horizon():
    rules = (
        {
            "model_id": "worker_signal_rsi_v1",
            "horizon_seconds": 3600,
            "mode": "ADVISORY",
        },
        {
            "model_id": "worker_signal_rsi_v1",
            "horizon_seconds": 3600,
            "regime": "quiet_range",
            "cohort_bucket": "mean_reversion",
            "mode": "ACTIVE",
        },
    )
    decision = resolve(rules)
    assert decision.mode == "ACTIVE"
    assert decision.specificity == 4

    other_regime = resolve(rules, regime="trend_expansion")
    assert other_regime.mode == "ADVISORY"
    assert other_regime.specificity == 2


def test_advisory_shadow_and_quarantine_never_enable_direct_influence():
    for mode in ("ADVISORY", "SHADOW", "QUARANTINED"):
        decision = resolve(({"model_id": "worker_signal_rsi_v1", "mode": mode},))
        assert decision.mode == mode
        assert decision.influence_enabled is False


def test_invalid_mode_is_ignored_instead_of_granting_influence():
    decision = resolve(({"model_id": "worker_signal_rsi_v1", "mode": "YOLO"},))
    assert decision.matched is False
    assert decision.mode is None
    assert decision.influence_enabled is False


def test_equal_specificity_uses_first_frozen_rule_deterministically():
    rules = (
        {"model_id": "worker_signal_rsi_v1", "horizon_seconds": 3600, "mode": "SHADOW"},
        {"model_id": "worker_signal_rsi_v1", "horizon_seconds": 3600, "mode": "ACTIVE"},
    )
    decision = resolve(rules)
    assert decision.mode == "SHADOW"
    assert decision.matched_rule_index == 0


def test_manifest_is_research_only_and_normalizes_rules():
    manifest = model_authority_manifest(
        (
            {
                "model_id": "worker_signal_rsi_v1",
                "horizon_seconds": "3600",
                "regime": "quiet_range",
                "mode": "active",
                "source": "test",
            },
            {"model_id": "", "mode": "ACTIVE"},
            {"model_id": "worker_signal_rsi2_v1", "mode": "INVALID"},
        )
    )
    assert manifest["schema"] == "hivenance_model_horizon_regime_authority_v1"
    assert manifest["execution_eligible"] is False
    assert manifest["promotion_eligible"] is False
    assert len(manifest["rules"]) == 1
    assert manifest["rules"][0]["mode"] == "ACTIVE"
    assert manifest["rules"][0]["horizon_seconds"] == 3600
