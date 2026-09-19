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
):
    return AblationSnapshot(
        forecast_id=fid,
        pair_id="A__B",
        forecast_timestamp_ms=1000,
        expected_net_bps=edge,
        expected_cost_bps=1.0,
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
    )


def settled(fid: str, net: float):
    return SettledRelativeForecast(
        schema="hivenance_settled_relative_forecast_v1",
        forecast_id=fid,
        pair_id="A__B",
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
