from strategies.relative_value_lab.full_organism_census_runner import (
    prosecute_mask,
    run_full_organism_census,
)
from strategies.relative_value_lab.historical_causal_prosecution import HistoricalWorldOutcome


def world(i, *, direction="UP", abstain=False, net=1.0, selected=True):
    return HistoricalWorldOutcome(
        world_state_id=f"ws-{i}",
        world_state_hash="sha256:"+str(i%10)*64,
        symbol="BTC/USD",
        timestamp_ms=1_000_000 + i*86_400_000,
        horizon_seconds=60,
        direction=direction,
        abstain=abstain,
        selected=selected,
        realized_net_bps=net,
    )


def test_prosecute_mask_measures_same_world_decision_and_net_delta():
    full=tuple(world(i,net=5.0) for i in range(6))
    blind=tuple(
        world(i,direction="ABSTAIN",abstain=True,net=0.0)
        for i in range(6)
    )
    row=prosecute_mask(
        mask_id="NO_STATISTICS",
        organ_id="statistics_bee",
        full_hive=full,
        ablated=blind,
        invoked_count=6,
        minimum_independent_worlds=5,
    )
    assert row.paired_world_count==6
    assert row.dependence_adjusted_world_count==6
    assert row.decision_change_count==6
    assert row.abstention_change_count==6
    assert row.historical_paired_delta_bps==5.0
    assert row.classification=="HISTORICALLY_USEFUL"


def test_census_builds_machine_readable_anatomy_report():
    full=tuple(world(i,net=4.0) for i in range(6))
    no_stats=tuple(world(i,net=1.0) for i in range(6))
    no_workers=tuple(
        world(i,direction="DOWN",net=-2.0)
        for i in range(6)
    )

    run=run_full_organism_census(
        outcomes_by_mask={
            "FULL_HIVE":full,
            "NO_STATISTICS":no_stats,
            "NO_WORKERS":no_workers,
        },
        invocation_counts={
            "NO_STATISTICS":6,
            "NO_WORKERS":6,
        },
    )

    assert set(run.paired_masks)=={"NO_STATISTICS","NO_WORKERS"}
    assert "NO_BAYES" in run.skipped_masks
    assert {
        row.organ_id
        for row in run.prosecution.organ_results
    }=={"statistics_bee","strategy_workers"}
    assert run.utility_census.historical_only is True
    assert run.execution_eligible is False


def test_census_requires_full_hive():
    import pytest
    with pytest.raises(ValueError,match="requires_full_hive"):
        run_full_organism_census(outcomes_by_mask={})



def test_mixed_cohort_worker_effect_stays_historically_mixed():
    full=[]
    blind=[]
    cohort_deltas=(10.0,-5.0,-4.0,-3.0,-2.0,-1.0,-0.5)
    for i,delta in enumerate(cohort_deltas):
        full.append(HistoricalWorldOutcome(
            world_state_id=f"obs-{i}",
            world_state_hash="sha256:"+str((i+1)%10)*64,
            symbol="BTC/USD",
            timestamp_ms=1_000_000+i,
            horizon_seconds=60,
            direction="UP",
            abstain=False,
            selected=True,
            realized_net_bps=delta,
            envelope_id="worker-model",
        ))
        blind.append(HistoricalWorldOutcome(
            world_state_id=f"obs-{i}",
            world_state_hash="sha256:"+str((i+1)%10)*64,
            symbol="BTC/USD",
            timestamp_ms=1_000_000+i,
            horizon_seconds=60,
            direction="ABSTAIN",
            abstain=True,
            selected=True,
            realized_net_bps=0.0,
            envelope_id="worker-model",
        ))
    row=prosecute_mask(
        mask_id="NO_WORKERS",
        organ_id="strategy_workers",
        full_hive=tuple(full),
        ablated=tuple(blind),
        invoked_count=7,
        minimum_independent_worlds=5,
    )
    assert row.dependence_adjusted_world_count==7
    assert row.classification=="HISTORICALLY_MIXED"
