import pytest

from strategies.relative_value_lab.statistical_synthesis import (
    StatisticalEvidence,
    StatisticsBee,
    SynthesisBee,
)


def ev(
    evidence_id: str,
    *,
    scope: str,
    observed: int,
    available: int,
    realized: float,
    positive: bool,
    root_char: str,
):
    return StatisticalEvidence(
        evidence_id=evidence_id,
        scope=scope,
        observed_at_ms=observed,
        available_at_ms=available,
        realized_bps=realized,
        positive=positive,
        evidence_root="sha256:" + root_char * 64,
    )


def test_statistics_bee_is_strictly_point_in_time():
    bee = StatisticsBee()
    bee.ingest_many(
        (
            ev("past", scope="exact", observed=10, available=20, realized=5, positive=True, root_char="a"),
            ev("same", scope="exact", observed=20, available=30, realized=100, positive=True, root_char="b"),
            ev("future", scope="exact", observed=30, available=40, realized=100, positive=True, root_char="c"),
        )
    )

    snap = bee.snapshot(scope="exact", as_of_ms=30)

    assert snap.n == 1
    assert snap.source_evidence_ids == ("past",)
    assert snap.evidence_cutoff_ms == 20
    assert snap.mean_bps == 5.0
    assert snap.execution_eligible is False
    assert snap.promotion_eligible is False


def test_statistics_bee_builds_bayesian_posterior_and_change_pressure():
    bee = StatisticsBee()
    returns = (-8, -5, -3, 4, 6, 8, 10, 12)
    for i, value in enumerate(returns):
        bee.ingest(
            ev(
                f"e{i}",
                scope="exact",
                observed=10 + i,
                available=20 + i,
                realized=value,
                positive=value > 0,
                root_char=chr(ord("a") + i),
            )
        )

    snap = bee.snapshot(scope="exact", as_of_ms=100)

    assert snap.n == 8
    assert snap.wins == 5
    assert 0.5 < snap.posterior_win_probability < 0.7
    assert snap.posterior_edge_positive_probability is not None
    assert 0.0 <= snap.change_point_pressure <= 1.0


def test_synthesis_bee_shrinks_sparse_exact_state_toward_broader_evidence():
    bee = StatisticsBee()

    bee.ingest(
        ev("exact-loss", scope="exact", observed=10, available=20, realized=-5, positive=False, root_char="a")
    )

    for i in range(16):
        bee.ingest(
            ev(
                f"class-{i}",
                scope="symbol_class",
                observed=30 + i,
                available=40 + i,
                realized=5 if i < 12 else -3,
                positive=i < 12,
                root_char="b",
            )
        )

    exact = bee.snapshot(scope="exact", as_of_ms=100)
    broad = bee.snapshot(scope="symbol_class", as_of_ms=100)

    state = SynthesisBee().synthesize(exact=exact, broader=((broad, 0.65),))

    assert exact.n == 1
    assert broad.n == 16
    assert state.hierarchical_win_probability > exact.posterior_win_probability
    assert state.scope_weights["exact"] > 0.0
    assert state.scope_weights["symbol_class"] > 0.0
    assert state.effective_sample_size == 17.0
    assert state.execution_eligible is False
    assert state.promotion_eligible is False


def test_statistics_snapshot_rejects_same_time_cutoff():
    from strategies.relative_value_lab.statistical_synthesis import StatisticsSnapshot

    with pytest.raises(ValueError, match="future_or_same_time"):
        StatisticsSnapshot(
            schema="hivenance_statistics_snapshot_v1",
            snapshot_id="stat_x",
            scope="exact",
            as_of_ms=10,
            evidence_cutoff_ms=10,
            n=1,
            effective_n=1.0,
            wins=1,
            losses=0,
            mean_bps=1.0,
            variance_bps2=0.0,
            std_bps=0.0,
            win_rate=1.0,
            posterior_win_probability=0.6,
            posterior_win_interval_90=(0.2, 0.9),
            posterior_edge_positive_probability=1.0,
            recent_mean_bps=None,
            prior_mean_bps=None,
            change_point_pressure=0.0,
            source_evidence_ids=("e",),
            evidence_roots=("sha256:" + "a" * 64,),
        )
