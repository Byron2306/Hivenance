from __future__ import annotations

from strategies.relative_value_lab.ablation_lab import (
    AblationSnapshot,
    RelativeValueAblationLab,
    admit,
)
from strategies.relative_value_lab.contracts import RELATIVE_VALUE_AUTHORITY
from strategies.relative_value_lab.settlement import SettledRelativeForecast


def snapshot(
    fid: str,
    *,
    resolution: str = "ADMIT_RESOLVED",
    dissent: bool = False,
    motion_kind: str = "FOLLOW",
    motion_bps: float = 1.5,
    edge: float = 1.5,
    stability: float = .65,
    lock: float = .9,
    pollen_count: int = 1,
    pollen_dissent: bool = False,
    srep: float = .6,
    mrep: float = .5,
    pair_id: str = "A__B",
    cost: float = 1.0,
):
    return AblationSnapshot(
        forecast_id=fid,
        pair_id=pair_id,
        forecast_timestamp_ms=1000,
        expected_net_bps=edge,
        expected_cost_bps=cost,
        stability_score=stability,
        quorum_formed=True,
        ensemble_lock=lock,
        explicit_dissent=dissent,
        motion_kind=motion_kind,
        motion_bps=motion_bps,
        queen_resolution=resolution,
        pollen_bounty_count=pollen_count,
        pollen_dissent_bounty=pollen_dissent,
        structural_reputation=srep,
        motion_reputation=mrep,
        motif_consonance=.7,
        motif_dissonance=.2,
        motif_tension=.2,
        motif_cadence_strength=.7,
        motif_counterpoint_diversity=.5,
        entrainment_strength=.65,
        false_unison_risk=.2,
        queen_polyphonic_pressure=.6,
        queen_tonal_coherence=.7,
        queen_timbral_diversity=.6,
        queen_pitch_convergence=.7,
        queen_subtle_shift=.3,
    )


def settled(fid: str, net: float, pair_id: str = "A__B"):
    return SettledRelativeForecast(
        schema="hivenance_settled_relative_forecast_v1",
        forecast_id=fid,
        pair_id=pair_id,
        model_id="test",
        forecast_timestamp_ms=1000,
        target_timestamp_ms=2000,
        settled_timestamp_ms=2000,
        horizon_seconds=1,
        direction="LONG_A_SHORT_B",
        entry_spread=0.0,
        settled_spread=0.001,
        predicted_signed_move_bps=10.0,
        realized_signed_move_bps=10.0,
        realized_directional_gross_bps=net+1.0,
        expected_cost_bps=1.0,
        realized_directional_net_bps=net,
        forecast_error_bps=0.0,
        abstain=False,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def test_counterpoint_ablation_differs_from_full_hive():
    s=snapshot(
        "f1",
        resolution="HOLD_COUNTERPOINT",
        dissent=True,
        motion_kind="DISSENT",
        motion_bps=2.0,
        pollen_dissent=True,
    )
    assert admit("FULL_HIVE",s) is False
    assert admit("NO_COUNTERPOINT_HOLD",s) is True
    assert admit("MOTION_DISSENT_ONLY",s) is True
    assert admit("MOTION_FOLLOW_ONLY",s) is False


def test_threshold_mutations_are_distinct():
    s=snapshot("f1",edge=1.5,stability=.65,lock=.8)
    assert admit("EDGE_GT_1",s) is True
    assert admit("EDGE_GT_2",s) is False
    assert admit("STABILITY_GT_060",s) is True
    assert admit("STABILITY_GT_070",s) is False
    assert admit("LOCK_GT_075",s) is True
    assert admit("LOCK_GT_090",s) is False


def test_deterministic_hash_controls_are_repeatable():
    s=snapshot("stable-id")
    values=[admit("HASH_50",s) for _ in range(5)]
    assert len(set(values))==1


def test_lab_reports_mutation_delta_against_full_hive():
    lab=RelativeValueAblationLab()
    # Full hive admits this +5.
    lab.freeze(snapshot("good",resolution="ADMIT_RESOLVED",dissent=False,motion_kind="FOLLOW"))
    lab.settle(settled("good",5.0))

    # Full hive holds this -8 because counterpoint is unresolved.
    lab.freeze(snapshot(
        "bad",resolution="HOLD_COUNTERPOINT",dissent=True,
        motion_kind="DISSENT",motion_bps=2.5,pollen_dissent=True,
    ))
    lab.settle(settled("bad",-8.0))

    report=lab.report()
    books={b.variant_id:b for b in report.books}
    assert books["FULL_HIVE"].cumulative_net_bps==5.0
    assert books["CONTROL_ALL"].cumulative_net_bps==-3.0
    assert books["NO_COUNTERPOINT_HOLD"].cumulative_net_bps==-3.0

    deltas={d.variant_id:d for d in lab.deltas()}
    assert deltas["NO_COUNTERPOINT_HOLD"].changed_decisions==1
    assert deltas["NO_COUNTERPOINT_HOLD"].cumulative_net_delta_bps==-8.0


def test_findings_do_not_overclaim_with_small_changed_sample():
    lab=RelativeValueAblationLab()
    lab.freeze(snapshot(
        "bad",resolution="HOLD_COUNTERPOINT",dissent=True,
        motion_kind="DISSENT",motion_bps=2.5,
    ))
    lab.settle(settled("bad",-8.0))
    findings={f.variant_id:f for f in lab.findings(minimum_changed_cases=5)}
    assert findings["NO_COUNTERPOINT_HOLD"].status=="INSUFFICIENT_CHANGED_CASES"


def test_no_pollen_and_no_reputation_expose_current_selection_non_effect():
    s=snapshot("f1",resolution="ADMIT_RESOLVED",pollen_count=0,srep=.1,mrep=.9)
    assert admit("FULL_HIVE",s) is True
    assert admit("NO_POLLEN",s) is True
    assert admit("NO_REPUTATION",s) is True

def test_queen_motif_entrainment_mutations_are_distinct():
    s=snapshot("f-music")
    assert admit("QUEEN_PRESSURE_GT_055",s) is True
    assert admit("QUEEN_TONAL_GT_050",s) is True
    assert admit("CADENCE_GT_065",s) is True
    assert admit("DISSONANCE_LT_025",s) is True
    assert admit("ENTRAINMENT_GT_060",s) is True
    assert admit("FALSE_UNISON_LT_025",s) is True

def test_interaction_mutations_are_distinct():
    s=snapshot(
        "combo",
        resolution="ADMIT_RESOLVED",
        dissent=False,
        motion_kind="FOLLOW",
        edge=1.5,
        stability=.65,
        pollen_count=1,
        srep=.7,
        mrep=.5,
    )
    assert admit("POLLEN_AND_REPUTATION",s) is True
    assert admit("QUORUM_PLUS_FOLLOW",s) is True
    assert admit("QUORUM_PLUS_EDGE1",s) is True
    assert admit("QUORUM_PLUS_EDGE2",s) is False
    assert admit("FOLLOW_PLUS_EDGE1",s) is True
    assert admit("FOLLOW_PLUS_STABILITY060",s) is True
    assert admit("FOLLOW_PLUS_LOW_COST_1",s) is True
    assert admit("FOLLOW_EDGE_COST_RATIO_1",s) is True
    assert admit("FOLLOW_MOTION_GE_EDGE",s) is True


def test_organ_findings_expose_selection_dead_weight():
    lab=RelativeValueAblationLab()
    for idx,net in enumerate((1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0),start=1):
        fid=f"f{idx}"
        lab.freeze(snapshot(fid,resolution="ADMIT_RESOLVED",pollen_count=1,srep=.6,mrep=.5))
        lab.settle(settled(fid,net))
    findings={f.organ_id:f for f in lab.organ_findings(minimum_changed_cases=3)}
    assert findings["pollen_bounties"].utility_status=="ZERO_SELECTION_EFFECT"
    assert findings["reputation"].utility_status=="ZERO_SELECTION_EFFECT"


def test_organ_findings_can_flag_harmful_candidate():
    lab=RelativeValueAblationLab()
    # FULL_HIVE holds dissenting losses. Removing counterpoint hold admits them.
    for idx in range(8):
        fid=f"bad{idx}"
        lab.freeze(snapshot(
            fid,
            resolution="HOLD_COUNTERPOINT",
            dissent=True,
            motion_kind="DISSENT",
            motion_bps=2.0,
        ))
        lab.settle(settled(fid,-5.0))
    findings={f.organ_id:f for f in lab.organ_findings(minimum_changed_cases=5)}
    # Removing counterpoint hold hurts performance, so counterpoint hold is useful.
    assert findings["counterpoint_hold"].utility_status=="USEFUL_CANDIDATE_THIS_SAMPLE"

def test_report_marks_reject_all_as_degenerate_select_none():
    lab=RelativeValueAblationLab()
    for idx,net in enumerate((2.0,-1.0,3.0),start=1):
        fid=f"d{idx}"
        lab.freeze(snapshot(fid))
        lab.settle(settled(fid,net))
    books={b.variant_id:b for b in lab.report().books}
    assert books["REJECT_ALL"].selected_count==0
    assert books["REJECT_ALL"].degenerate_select_none is True
    assert books["CONTROL_ALL"].degenerate_select_all is True
    assert books["CONTROL_ALL"].selection_rate==1.0


def test_selector_equivalence_exposes_policy_aliases():
    lab=RelativeValueAblationLab()
    # In this constructed path FULL_HIVE, NO_POLLEN and NO_REPUTATION are exact aliases.
    for idx in range(4):
        fid=f"eq{idx}"
        lab.freeze(snapshot(fid,resolution="ADMIT_RESOLVED"))
        lab.settle(settled(fid,1.0))
    classes=lab.selector_equivalence_classes()
    alias_sets=[set(row.variant_ids) for row in classes]
    assert any(
        {"FULL_HIVE","NO_POLLEN","NO_REPUTATION"}.issubset(group)
        for group in alias_sets
    )


def test_variant_stability_detects_best_pair_dependency():
    lab=RelativeValueAblationLab()
    rows=[
        ("s1","A__B",6.0),
        ("s2","A__B",5.0),
        ("s3","C__D",-2.0),
        ("s4","C__D",-2.0),
    ]
    for fid,pair,net in rows:
        lab.freeze(snapshot(fid,pair_id=pair))
        lab.settle(settled(fid,net,pair_id=pair))
    stability={row.variant_id:row for row in lab.variant_stability()}
    full=stability["FULL_HIVE"]
    assert full.best_pair_id=="A__B"
    assert full.net_without_best_pair_bps==-4.0
    assert full.survives_best_pair_removal is False


def test_variant_stability_detects_temporal_fragility():
    lab=RelativeValueAblationLab()
    for idx,net in enumerate((4.0,3.0,-5.0,-4.0),start=1):
        fid=f"t{idx}"
        lab.freeze(snapshot(fid))
        lab.settle(settled(fid,net))
    stability={row.variant_id:row for row in lab.variant_stability()}
    full=stability["FULL_HIVE"]
    assert full.first_half_net_bps==7.0
    assert full.second_half_net_bps==-9.0
    assert full.both_halves_positive is False


def test_cost_motion_interactions_do_not_alias_by_definition():
    low=snapshot("low",motion_kind="FOLLOW",motion_bps=3.0,edge=2.0,cost=.5)
    high=snapshot("high",motion_kind="FOLLOW",motion_bps=1.0,edge=2.0,cost=2.5)
    assert admit("FOLLOW_PLUS_LOW_COST_1",low) is True
    assert admit("FOLLOW_PLUS_LOW_COST_1",high) is False
    assert admit("FOLLOW_EDGE_COST_RATIO_2",low) is True
    assert admit("FOLLOW_EDGE_COST_RATIO_2",high) is False
    assert admit("FOLLOW_MOTION_GE_EDGE",low) is True
    assert admit("FOLLOW_MOTION_GE_EDGE",high) is False
