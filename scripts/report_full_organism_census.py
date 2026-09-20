from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from strategies.relative_value_lab.full_organism_census_runner import run_full_organism_census
from strategies.relative_value_lab.historical_causal_prosecution import HistoricalWorldOutcome
from strategies.relative_value_lab.organ_route_census import build_route_census
from strategies.relative_value_lab.organ_runtime_control import build_runtime_control_plane


def _load_bundle(path: str) -> dict[str, Any]:
    payload=json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema")!="hivenance_full_organism_census_replay_bundle_v1":
        raise ValueError("unsupported_census_bundle_schema:" + str(payload.get("schema")))
    return payload


def _outcomes(rows):
    return tuple(HistoricalWorldOutcome(**row) for row in rows)


def _outcome_key(row: HistoricalWorldOutcome):
    return (
        str(row.world_state_id),
        str(row.symbol),
        int(row.timestamp_ms),
        int(row.horizon_seconds),
        str(row.model_id or ""),
        str(row.envelope_id or ""),
    )


def _merge_full_hive(existing, incoming):
    """Merge compatible FULL_HIVE references from different prosecution runners.

    Different runners may emit different subsets/model rows for the same frozen
    worlds. Overlapping rows must agree on realized outcomes; non-overlapping
    rows are unioned. This exception applies only to FULL_HIVE.
    """
    by_key={_outcome_key(row):row for row in existing}
    for row in incoming:
        key=_outcome_key(row)
        prior=by_key.get(key)
        if prior is None:
            by_key[key]=row
            continue
        if (
            prior.realized_net_bps != row.realized_net_bps
            or prior.selected != row.selected
            or prior.world_state_hash != row.world_state_hash
        ):
            raise ValueError("conflicting_replay_mask:FULL_HIVE")
    return tuple(
        by_key[key]
        for key in sorted(by_key)
    )


def main() -> None:
    parser=argparse.ArgumentParser(
        description="Run the Hivenance Phase 12.8 full-organism historical census over strict replay bundles."
    )
    parser.add_argument(
        "--bundle",
        action="append",
        required=True,
        help="Replay bundle JSON. May be repeated; later bundles may add masks but may not conflict.",
    )
    parser.add_argument(
        "--out",
        default="data/full_organism_census.json",
        help="Output JSON report path.",
    )
    parser.add_argument(
        "--minimum-independent-worlds",
        type=int,
        default=5,
    )
    args=parser.parse_args()

    outcomes_by_mask={}
    invocation_counts={}
    worker_component_causality={}
    adversarial_attacks={}
    explicit_unavailable_masks={}
    control_masks_prosecuted={}
    sources=[]

    for path in args.bundle:
        bundle=_load_bundle(path)
        sources.append({
            "path":path,
            "source":bundle.get("source"),
            "strict_before":bundle.get("strict_before"),
            "evidence_lag_sec":bundle.get("evidence_lag_sec"),
            "warning_floor":bundle.get("warning_floor"),
        })
        for mask_id,rows in dict(bundle.get("outcomes_by_mask") or {}).items():
            parsed=_outcomes(rows)
            existing=outcomes_by_mask.get(mask_id)
            if existing is not None:
                if str(mask_id)=="FULL_HIVE":
                    outcomes_by_mask[mask_id]=_merge_full_hive(existing,parsed)
                    continue
                if tuple(x.to_dict() for x in existing)!=tuple(x.to_dict() for x in parsed):
                    raise ValueError("conflicting_replay_mask:" + str(mask_id))
            outcomes_by_mask[mask_id]=parsed
        for mask_id,count in dict(bundle.get("invocation_counts") or {}).items():
            invocation_counts[mask_id]=max(int(invocation_counts.get(mask_id,0)),int(count))
        for mask_id,row in dict(bundle.get("worker_component_causality") or {}).items():
            existing=worker_component_causality.get(mask_id)
            if existing is not None and existing!=row:
                raise ValueError("conflicting_worker_component_causality:" + str(mask_id))
            worker_component_causality[mask_id]=row
        for attack_id,row in dict(bundle.get("adversarial_attacks") or {}).items():
            existing=adversarial_attacks.get(attack_id)
            if existing is not None and existing!=row:
                raise ValueError("conflicting_adversarial_attack:" + str(attack_id))
            adversarial_attacks[attack_id]=row
        for mask_id,reason in dict(bundle.get("explicit_unavailable_masks") or {}).items():
            existing=explicit_unavailable_masks.get(mask_id)
            if existing is not None and existing!=reason:
                raise ValueError("conflicting_explicit_unavailable_mask:" + str(mask_id))
            explicit_unavailable_masks[mask_id]=reason
        for mask_id,row in dict(bundle.get("control_masks_prosecuted") or {}).items():
            existing=control_masks_prosecuted.get(mask_id)
            if existing is not None and existing!=row:
                raise ValueError("conflicting_control_mask_prosecution:" + str(mask_id))
            control_masks_prosecuted[mask_id]=row

    run=run_full_organism_census(
        outcomes_by_mask=outcomes_by_mask,
        invocation_counts=invocation_counts,
        minimum_independent_worlds=int(args.minimum_independent_worlds),
    )

    runtime_seen_ids=set()
    runtime_invocations={}
    mask_to_runtime={
        "NO_LEARNING":"learning_memory",
        "NO_CRYSTALS":"crystals",
        "NO_WORKERS":"strategy_workers",
        "NO_STATISTICS":"statistics_bee",
        "NO_BAYES":"bayesian_regime_filter",
        "NO_EXTERNAL":"external_statistics_sensorium",
        "NO_CONFORMAL":"stochastic_calibration",
        "NO_ML":"ml_challenger",
    }
    for mask_id,count in invocation_counts.items():
        runtime_id=mask_to_runtime.get(mask_id)
        if runtime_id:
            runtime_seen_ids.add(runtime_id)
            runtime_invocations[runtime_id]=int(count)

    route=build_route_census(
        invocation_counts=runtime_invocations,
        runtime_seen_ids=tuple(sorted(runtime_seen_ids)),
        measured_ids=tuple(sorted(runtime_seen_ids)),
    )

    utility_rows = [row.to_dict() for row in run.utility_census.rows]
    runtime_plane = build_runtime_control_plane(utility_rows)

    payload={
        "schema":"hivenance_full_organism_census_report_v1",
        "sources":sources,
        "historical_only":True,
        "prospective_usefulness_proven":False,
        "execution_eligible":False,
        "promotion_eligible":False,
        "paired_masks":run.paired_masks,
        "skipped_masks":run.skipped_masks,
        "skipped_mask_reason":"SKIPPED_NO_HISTORICAL_RECONSTRUCTION",
        "historical_prosecution":run.prosecution.to_dict(),
        "organ_utility_census":run.utility_census.to_dict(),
        "organ_route_census":route.to_dict(),
        "worker_component_causality":worker_component_causality,
        "adversarial_attacks":adversarial_attacks,
        "explicit_unavailable_masks":explicit_unavailable_masks,
        "control_masks_prosecuted":control_masks_prosecuted,
        "organ_runtime_control": {
            organ_id: state.to_dict()
            for organ_id,state in sorted(runtime_plane.items())
        },
    }

    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,sort_keys=True,indent=2),encoding="utf-8")

    print("HIVENANCE_FULL_ORGANISM_CENSUS")
    print("historical_only=True")
    print("prospective_usefulness_proven=False")
    print("paired_masks=",",".join(run.paired_masks) if run.paired_masks else "none")
    print("skipped_masks=",",".join(run.skipped_masks) if run.skipped_masks else "none")
    print("useful_organs=",",".join(run.utility_census.useful_organs) if run.utility_census.useful_organs else "none")
    print("harmful_organs=",",".join(run.utility_census.harmful_organs) if run.utility_census.harmful_organs else "none")
    print("inert_organs=",",".join(run.utility_census.inert_organs) if run.utility_census.inert_organs else "none")
    print("underpowered_organs=",",".join(run.utility_census.underpowered_organs) if run.utility_census.underpowered_organs else "none")
    print("mixed_organs=",",".join(run.utility_census.mixed_organs) if run.utility_census.mixed_organs else "none")
    if worker_component_causality:
        print("worker_components=")
        for mask_id,row in sorted(worker_component_causality.items()):
            print(
                " ",
                mask_id,
                row.get("classification"),
                row.get("recommendation"),
            )
    print("organ_runtime_modes=")
    for organ_id,state in sorted(runtime_plane.items()):
        print(
            " ",
            organ_id,
            state.mode,
            "influence=" + str(state.influence_enabled),
            "shadow_probe=" + str(state.shadow_probe_enabled),
            state.reason,
        )
    print("dead_routes=",",".join(route.dead_routes) if route.dead_routes else "none")
    print("unmeasured_routes=",",".join(route.unmeasured_routes) if route.unmeasured_routes else "none")
    print("report=",str(out))


if __name__=="__main__":
    main()
