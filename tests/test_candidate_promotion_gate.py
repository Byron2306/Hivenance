from __future__ import annotations

from strategies.volatility_breakout.candidate_promotion_gate import (
    SettledForecast,
    block_bootstrap_lower_bound,
    chronological_holdout,
    cost_stress_holdout,
    episode_concentration_check,
    evaluate_candidate,
    independent_bucket_check,
)

HOUR = 3600.0
DAY = 86400.0


def _rows(specs):
    """specs: list of (ts, directional_bps, net_bps)."""
    return [SettledForecast(ts=ts, directional_return_bps=g, net_return_bps=n) for ts, g, n in specs]


def test_insufficient_evidence_below_min_settled():
    rows = _rows([(i * HOUR, 5.0, 2.0) for i in range(10)])
    result = evaluate_candidate(rows, min_settled=100)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["promotion"] == "RESEARCH_ONLY"


def test_temporal_decay_detected_when_second_half_negative():
    n = 200
    rows = []
    for i in range(n):
        ts = i * HOUR
        # first half strongly positive, second half strongly negative
        net = 10.0 if i < n // 2 else -10.0
        rows.append((ts, net + 2.0, net))
    result = evaluate_candidate(_rows(rows), min_settled=100, min_hourly_buckets=24, min_days=3)
    assert result["status"] == "TEMPORAL_DECAY"
    assert result["promotion"] == "REVOKED"


def test_negative_capability_when_both_halves_negative():
    n = 200
    rows = [(i * HOUR, -3.0, -5.0) for i in range(n)]
    result = evaluate_candidate(_rows(rows), min_settled=100)
    assert result["status"] == "NEGATIVE_CAPABILITY"
    assert result["promotion"] == "REFUSED"


def test_validated_candidate_passes_all_gates():
    # 200 rows spread across >24 distinct hours and >3 days, small positive
    # net every row, spread evenly so no concentration and stable under
    # bootstrap/cost stress.
    n = 240
    rows = []
    for i in range(n):
        ts = i * (DAY / 24.0)  # 10 rows/day-ish spacing across many hours/days
        rows.append((ts, 6.0, 4.0))
    result = evaluate_candidate(
        _rows(rows), min_settled=100, min_hourly_buckets=24, min_days=3, n_boot=200
    )
    assert result["status"] == "VALIDATED_CANDIDATE"
    assert result["promotion"] == "PROMOTE_ELIGIBLE"
    assert all(result["gates"].values())


def test_prospective_challenger_low_margin_when_only_cost_stress_fails():
    # Positive but thin edge: net is barely positive, so 1.5x cost stress
    # (which increases the cost, i.e. gross-net gap) flips it negative,
    # while still passing bucket/bootstrap/concentration gates.
    n = 240
    rows = []
    for i in range(n):
        ts = i * (DAY / 24.0)
        # cost = gross - net = 9.5, net = 0.5 -> thin margin
        rows.append((ts, 10.0, 0.5))
    result = evaluate_candidate(
        _rows(rows), min_settled=100, min_hourly_buckets=24, min_days=3, n_boot=200
    )
    assert result["status"] == "PROSPECTIVE_CHALLENGER_LOW_MARGIN"
    assert result["promotion"] == "RESEARCH_ONLY"
    assert result["gates"]["cost_stress"] is False


def test_prospective_challenger_when_episode_concentrated():
    # All evidence positive but 90% of the total profit comes from a single
    # hour -> should fail episode_concentration (and likely bootstrap too).
    n = 150
    rows = [(i * HOUR, 1.2, 1.0) for i in range(n)]
    rows.append((n * HOUR, 500.0, 400.0))  # one dominating hour
    result = evaluate_candidate(
        _rows(rows), min_settled=100, min_hourly_buckets=24, min_days=3, n_boot=200
    )
    assert result["status"] in ("PROSPECTIVE_CHALLENGER", "PROSPECTIVE_CHALLENGER_LOW_MARGIN")
    assert result["gates"]["episode_concentration"] is False


def test_chronological_holdout_uses_newest_slice():
    rows = _rows([(i * HOUR, 1.0, -5.0 if i < 60 else 5.0) for i in range(100)])
    result = chronological_holdout(rows, holdout_frac=0.4)
    assert result["n"] == 40
    assert result["positive"] is True


def test_cost_stress_holdout_amplifies_cost_gap():
    rows = _rows([(i * HOUR, 10.0, 1.0) for i in range(100)])
    result = cost_stress_holdout(rows, holdout_frac=0.4, cost_multiplier=1.5)
    # cost = 9, stressed_net = 10 - 1.5*9 = -3.5
    assert result["mean_stressed_net_bps"] == -3.5
    assert result["positive"] is False


def test_independent_bucket_check_counts_distinct_hours_and_days():
    rows = _rows([(i * HOUR, 1.0, 1.0) for i in range(50)])
    result = independent_bucket_check(rows, min_hourly_buckets=24, min_days=3, min_settled=50)
    assert result["distinct_hourly_buckets"] == 50
    assert result["passes"] is True


def test_block_bootstrap_lower_bound_positive_for_stable_edge():
    rows = _rows([(i * HOUR, 3.0, 2.0) for i in range(100)])
    result = block_bootstrap_lower_bound(rows, n_boot=300, seed=42)
    assert result["passes"] is True
    assert result["lower_bound_bps"] > 0


def test_episode_concentration_fails_on_nonpositive_total():
    rows = _rows([(i * HOUR, -1.0, -1.0) for i in range(20)])
    result = episode_concentration_check(rows)
    assert result["passes"] is False
