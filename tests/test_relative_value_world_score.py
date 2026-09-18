from __future__ import annotations

import pytest

from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreBindingClaim,
    ScoreObservation,
)


def obs(
    observation_id,
    source_id,
    observed_at_ms,
    *,
    scope="pair:A/B",
    payload=None,
    evidence_char="1",
):
    return ScoreObservation(
        observation_id=observation_id,
        source_id=source_id,
        source_class="public_market",
        scope=scope,
        observed_at_ms=observed_at_ms,
        received_at_ms=observed_at_ms+5,
        evidence_root="sha256:"+evidence_char*64,
        payload=payload or {"bid":100.0,"ask":100.1},
    )


def frame():
    return CanonicalWorldScore.assemble(
        observations=(
            obs("o1","kraken-book:A/B",1000,evidence_char="1"),
            obs("o2","kraken-trades:A/B",1010,payload={"last":100.05},evidence_char="2"),
        ),
        assembled_at_ms=1020,
        freshness_window_ms=15000,
    )


def test_same_observed_score_produces_same_binding():
    a=frame()
    b=frame()
    assert a.world_state_id==b.world_state_id
    assert a.world_state_hash==b.world_state_hash
    assert a.observed_digest==b.observed_digest


def test_observation_order_does_not_change_score_page():
    first=CanonicalWorldScore.assemble(
        observations=(obs("a","s1",1000),obs("b","s2",1010,evidence_char="2")),
        assembled_at_ms=1020,
    )
    second=CanonicalWorldScore.assemble(
        observations=(obs("b","s2",1010,evidence_char="2"),obs("a","s1",1000)),
        assembled_at_ms=1020,
    )
    assert first.world_state_hash==second.world_state_hash


def test_future_observation_is_forbidden():
    with pytest.raises(ValueError,match="future_observation_forbidden"):
        CanonicalWorldScore.assemble(
            observations=(obs("future","s1",2000),),
            assembled_at_ms=1000,
        )


def test_conflicting_same_source_same_time_is_forbidden():
    with pytest.raises(ValueError,match="conflicting_same_source_observation"):
        CanonicalWorldScore.assemble(
            observations=(
                obs("a","kraken-book:A/B",1000,payload={"bid":100}),
                obs("b","kraken-book:A/B",1000,payload={"bid":101},evidence_char="2"),
            ),
            assembled_at_ms=1010,
        )


def test_interpretation_cites_parent_without_mutating_observed_digest():
    f=frame()
    before=f.observed_digest
    interpretation=CanonicalWorldScore.interpretation(
        f,
        interpretation_id="i1",
        organ_id="pair_lab",
        created_at_ms=1030,
        evidence_roots=("sha256:"+"3"*64,),
        payload={"spread_zscore":2.1},
    )
    assert interpretation.parent_world_state_id==f.world_state_id
    assert interpretation.parent_world_state_hash==f.world_state_hash
    assert f.observed_digest==before
    assert interpretation.execution_eligible is False


def test_binding_audit_detects_one_organ_on_wrong_score_page():
    f=frame()
    audit=CanonicalWorldScore.audit_bindings(
        f,
        claims=(
            ScoreBindingClaim("queen",f.world_state_id,f.world_state_hash,"interpreted_research"),
            ScoreBindingClaim("bee-a",f.world_state_id,f.world_state_hash,"observed_market"),
            ScoreBindingClaim("bee-b","ws_wrong","sha256:"+"f"*64,"observed_market"),
        ),
        now_ms=2000,
    )
    assert audit.all_observed_claimants_bound is False
    assert "bee-b" in audit.refused_claimants
    assert any(v.startswith("world_score_binding_drift:bee-b") for v in audit.violations)


def test_synthetic_branch_is_separate_from_observed_binding_completeness():
    f=frame()
    audit=CanonicalWorldScore.audit_bindings(
        f,
        claims=(
            ScoreBindingClaim("queen",f.world_state_id,f.world_state_hash,"interpreted_research"),
            ScoreBindingClaim(
                "mystique-world",
                f.world_state_id,
                f.world_state_hash,
                "synthetic_counterfactual",
                synthetic=True,
            ),
        ),
        now_ms=2000,
    )
    assert audit.all_observed_claimants_bound is True
    assert audit.synthetic_claimants==("mystique-world",)


def test_stale_frame_is_explicitly_not_fresh():
    f=frame()
    audit=CanonicalWorldScore.audit_bindings(
        f,
        claims=(ScoreBindingClaim("queen",f.world_state_id,f.world_state_hash,"interpreted_research"),),
        now_ms=f.expires_at_ms+1,
    )
    assert audit.all_observed_claimants_bound is False
    assert "canonical_score_frame_stale" in audit.violations
