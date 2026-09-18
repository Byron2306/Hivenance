from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

"""Statistical promotion/demotion gate for research candidates.

A naive "mean net_return_bps > 0 across all history" check is trivially
fooled by: (a) an edge that existed early and has since decayed away,
(b) evidence concentrated in a single correlated episode (one volatile hour),
(c) too few independent observations to distinguish signal from noise, and
(d) an edge that only survives because realized costs happened to run
slightly below what a real deployment would pay.

This module applies six independent checks before a candidate is allowed to
move past RESEARCH_ONLY:

1. Positive chronological holdout -- the newest slice of evidence (by
   default the most recent 40%) must itself be net-positive. A candidate
   that was only positive early is decaying, not durable.
2. Independent observation buckets -- evidence is counted by distinct
   *hourly* buckets (and distinct calendar days), not raw forecast rows,
   because forecasts inside the same hour are highly correlated (same
   underlying market move). Too few independent buckets means the sample
   size is really much smaller than the row count suggests.
3. Block-bootstrap lower bound -- resampling whole hourly blocks (not
   individual rows) preserves within-hour correlation; the candidate must
   have a positive lower-bound (default 5th percentile) mean under this
   resampling.
4. No episode concentration -- no single hourly bucket may contribute more
   than a bounded share (default 30%) of total realized profit; otherwise
   the "edge" is really one lucky trade.
5. Cost-stress survival -- the chronological holdout must remain positive
   even if realized trading costs were 1.5x what was actually observed,
   as a margin-of-safety against fee/slippage estimation error.
6. Prospective confirmation -- handled by pre-registering the hypothesis
   (see hypothesis_registry.py) and only counting forecasts created after
   the registration timestamp as confirming evidence going forward.

This module does not touch the database or execute trades. It only
classifies already-settled (forecast, outcome) evidence.
"""


@dataclass(frozen=True)
class SettledForecast:
    """ts: forecast timestamp.

    directional_return_bps: the direction-adjusted, pre-cost return -- i.e.
    what hypothesis_outcomes.directional_return_bps stores (+raw market move
    for UP forecasts, -raw market move for DOWN forecasts). This is NOT the
    same as hypothesis_outcomes.gross_return_bps, which is the raw, UNSIGNED
    market move regardless of forecast direction -- using gross_return_bps
    here would silently corrupt the cost-stress calculation below.

    net_return_bps: directional_return_bps minus realized cost (the actual
    realized P&L).
    """

    ts: float
    directional_return_bps: float
    net_return_bps: float


def hour_bucket(ts: float) -> int:
    return int(ts // 3600)


def day_bucket(ts: float) -> int:
    return int(ts // 86400)


def chronological_holdout(
    rows: Sequence[SettledForecast], holdout_frac: float = 0.4
) -> dict:
    """Mean net_return_bps over the newest `holdout_frac` share of evidence."""
    ordered = sorted(rows, key=lambda r: r.ts)
    n = len(ordered)
    cut = max(0, n - max(1, int(round(n * holdout_frac))))
    holdout = ordered[cut:]
    if not holdout:
        return {"n": 0, "mean_net_bps": None, "positive": False}
    mean = sum(r.net_return_bps for r in holdout) / len(holdout)
    return {"n": len(holdout), "mean_net_bps": mean, "positive": mean > 0}


def cost_stress_holdout(
    rows: Sequence[SettledForecast],
    holdout_frac: float = 0.4,
    cost_multiplier: float = 1.5,
) -> dict:
    """Re-derives net_return_bps on the holdout as if costs were `cost_multiplier`x.

    cost = directional - net (as actually realized);
    stressed_net = directional - cost_multiplier * cost.
    """
    ordered = sorted(rows, key=lambda r: r.ts)
    n = len(ordered)
    cut = max(0, n - max(1, int(round(n * holdout_frac))))
    holdout = ordered[cut:]
    if not holdout:
        return {"n": 0, "mean_stressed_net_bps": None, "positive": False}
    stressed = []
    for r in holdout:
        cost = r.directional_return_bps - r.net_return_bps
        stressed.append(r.directional_return_bps - cost_multiplier * cost)
    mean = sum(stressed) / len(stressed)
    return {"n": len(stressed), "mean_stressed_net_bps": mean, "positive": mean > 0}


def independent_bucket_check(
    rows: Sequence[SettledForecast],
    min_hourly_buckets: int = 24,
    min_days: int = 3,
    min_settled: int = 100,
) -> dict:
    hours = {hour_bucket(r.ts) for r in rows}
    days = {day_bucket(r.ts) for r in rows}
    passes = (
        len(hours) >= min_hourly_buckets
        and len(days) >= min_days
        and len(rows) >= min_settled
    )
    return {
        "distinct_hourly_buckets": len(hours),
        "distinct_days": len(days),
        "n_settled": len(rows),
        "passes": passes,
    }


def block_bootstrap_lower_bound(
    rows: Sequence[SettledForecast],
    n_boot: int = 2000,
    lower_pct: float = 5.0,
    seed: int = 1337,
) -> dict:
    """Resamples whole hourly blocks (with replacement) to preserve
    within-hour correlation, and reports the lower_pct percentile of the
    resulting distribution of bootstrap means."""
    buckets: dict[int, list] = {}
    for r in rows:
        buckets.setdefault(hour_bucket(r.ts), []).append(r.net_return_bps)
    block_list = list(buckets.values())
    if not block_list:
        return {"lower_bound_bps": None, "n_boot": 0, "n_blocks": 0, "passes": False}
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sampled_blocks = [block_list[rng.randrange(len(block_list))] for _ in range(len(block_list))]
        flat = [v for block in sampled_blocks for v in block]
        if flat:
            means.append(sum(flat) / len(flat))
    means.sort()
    if not means:
        return {"lower_bound_bps": None, "n_boot": 0, "n_blocks": len(block_list), "passes": False}
    idx = min(len(means) - 1, max(0, int(round(len(means) * (lower_pct / 100.0))) - 1))
    lower = means[idx]
    return {
        "lower_bound_bps": lower,
        "n_boot": len(means),
        "n_blocks": len(block_list),
        "passes": lower > 0,
    }


def episode_concentration_check(
    rows: Sequence[SettledForecast], max_share: float = 0.30
) -> dict:
    """Fails (passes=False) if total profit is non-positive (nothing to
    concentrate/attribute), or if any single hourly bucket accounts for
    more than `max_share` of total realized profit."""
    buckets: dict[int, float] = {}
    for r in rows:
        buckets[hour_bucket(r.ts)] = buckets.get(hour_bucket(r.ts), 0.0) + r.net_return_bps
    total = sum(buckets.values())
    if total <= 0 or not buckets:
        return {"max_single_hour_share": None, "total_bps": total, "passes": False}
    max_share_actual = max(buckets.values()) / total
    return {
        "max_single_hour_share": max_share_actual,
        "total_bps": total,
        "passes": max_share_actual <= max_share,
    }


def evaluate_candidate(
    rows: Sequence[SettledForecast],
    *,
    holdout_frac: float = 0.4,
    min_hourly_buckets: int = 24,
    min_days: int = 3,
    min_settled: int = 100,
    max_episode_share: float = 0.30,
    cost_stress_multiplier: float = 1.5,
    n_boot: int = 2000,
) -> dict:
    """Classifies a candidate's evidence and returns a ledger-ready verdict.

    Status/promotion vocabulary:
      - INSUFFICIENT_EVIDENCE / RESEARCH_ONLY: fewer than min_settled rows.
      - TEMPORAL_DECAY / REVOKED: first-half positive, second-half <= 0.
      - NEGATIVE_CAPABILITY / REFUSED: both halves <= 0.
      - VALIDATED_CANDIDATE / PROMOTE_ELIGIBLE: second half positive AND all
        of (buckets, bootstrap, concentration, cost-stress) pass.
      - PROSPECTIVE_CHALLENGER(_LOW_MARGIN) / RESEARCH_ONLY: second half
        positive but one or more rigor gates fail. LOW_MARGIN specifically
        flags candidates that fail the cost-stress test (i.e. the edge is
        thin enough that it disappears under a modest cost-estimation
        error), since that is a materially weaker case than failing only
        on bucket-count/concentration.
    """
    ordered = sorted(rows, key=lambda r: r.ts)
    n = len(ordered)
    if n < min_settled:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "promotion": "RESEARCH_ONLY",
            "reason": f"only {n} settled forecasts (< {min_settled} required)",
            "n_settled": n,
        }

    half = n // 2
    first_half = ordered[:half]
    second_half = ordered[half:]
    first_mean = sum(r.net_return_bps for r in first_half) / len(first_half) if first_half else None
    second_mean = sum(r.net_return_bps for r in second_half) / len(second_half) if second_half else None

    if first_mean is not None and second_mean is not None and first_mean > 0 and second_mean <= 0:
        return {
            "status": "TEMPORAL_DECAY",
            "promotion": "REVOKED",
            "reason": "chronological holdout mean negative",
            "n_settled": n,
            "first_half_mean_bps": first_mean,
            "second_half_mean_bps": second_mean,
        }

    if first_mean is not None and second_mean is not None and first_mean <= 0 and second_mean <= 0:
        return {
            "status": "NEGATIVE_CAPABILITY",
            "promotion": "REFUSED",
            "reason": "negative in both chronological halves",
            "n_settled": n,
            "first_half_mean_bps": first_mean,
            "second_half_mean_bps": second_mean,
        }

    holdout = chronological_holdout(ordered, holdout_frac)
    buckets = independent_bucket_check(ordered, min_hourly_buckets, min_days, min_settled)
    boot = block_bootstrap_lower_bound(ordered, n_boot=n_boot)
    conc = episode_concentration_check(ordered, max_episode_share)
    stress = cost_stress_holdout(ordered, holdout_frac, cost_stress_multiplier)

    gates = {
        "chronological_holdout": bool(holdout["positive"]),
        "independent_buckets": bool(buckets["passes"]),
        "block_bootstrap": bool(boot["passes"]),
        "episode_concentration": bool(conc["passes"]),
        "cost_stress": bool(stress["positive"]),
    }
    failing = [name for name, ok in gates.items() if not ok]

    detail = {
        "n_settled": n,
        "first_half_mean_bps": first_mean,
        "second_half_mean_bps": second_mean,
        "chronological_holdout": holdout,
        "independent_buckets": buckets,
        "block_bootstrap": boot,
        "episode_concentration": conc,
        "cost_stress": stress,
        "gates": gates,
    }

    if not failing:
        detail.update({
            "status": "VALIDATED_CANDIDATE",
            "promotion": "PROMOTE_ELIGIBLE",
            "reason": "passes all promotion gates: positive holdout, positive bootstrap lower bound, "
            "sufficient independent buckets, no single-hour concentration, survives 1.5x cost stress",
        })
        return detail

    if "cost_stress" in failing and len(failing) <= 2:
        stressed_mean = stress.get("mean_stressed_net_bps")
        margin = f"{stressed_mean:.2f}" if stressed_mean is not None else "n/a"
        detail.update({
            "status": "PROSPECTIVE_CHALLENGER_LOW_MARGIN",
            "promotion": "RESEARCH_ONLY",
            "reason": f"second-half edge does not survive 1.5x cost stress (stressed mean {margin} bps)"
            + (f"; also failing: {', '.join(f for f in failing if f != 'cost_stress')}" if len(failing) > 1 else ""),
        })
        return detail

    detail.update({
        "status": "PROSPECTIVE_CHALLENGER",
        "promotion": "RESEARCH_ONLY",
        "reason": f"positive second half, but fails rigor gate(s): {', '.join(failing)}",
    })
    return detail
