from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ReplicationContract:
    minimum_fills: int = 30
    minimum_symbols: int = 10
    maximum_symbol_fraction: float = 0.30
    require_positive_median_gross: bool = True
    require_positive_median_net: bool = True
    require_positive_excess_vs_control: bool = True


def _median(values: Sequence[float]) -> float | None:
    xs = [float(x) for x in values]
    return statistics.median(xs) if xs else None


def _mean(values: Sequence[float]) -> float | None:
    xs = [float(x) for x in values]
    return statistics.mean(xs) if xs else None


def _normal_ci(values: Sequence[float]) -> tuple[float | None, float | None]:
    xs = [float(x) for x in values]
    if len(xs) < 2:
        return None, None
    mu = statistics.mean(xs)
    se = statistics.stdev(xs) / math.sqrt(len(xs))
    return mu - 1.96 * se, mu + 1.96 * se


def time_block_summary(rows: Sequence[Mapping[str, Any]], blocks: int = 4) -> dict[str, Any]:
    ordered = sorted(
        [r for r in rows if r.get("realized_net_bps") is not None],
        key=lambda r: int(r.get("timestamp_ms") or 0),
    )
    if not ordered:
        return {"blocks": 0, "block_means_bps": [], "mean_bps": None, "ci95_low_bps": None, "ci95_high_bps": None}
    k = max(1, min(int(blocks), len(ordered)))
    means = []
    for i in range(k):
        lo = (i * len(ordered)) // k
        hi = ((i + 1) * len(ordered)) // k
        vals = [float(r["realized_net_bps"]) for r in ordered[lo:hi]]
        if vals:
            means.append(statistics.mean(vals))
    ci_lo, ci_hi = _normal_ci(means)
    return {
        "blocks": len(means),
        "block_means_bps": means,
        "mean_bps": _mean(means),
        "ci95_low_bps": ci_lo,
        "ci95_high_bps": ci_hi,
    }


def leave_one_symbol_out(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if r.get("realized_net_bps") is not None and str(r.get("symbol") or "")]
    symbols = sorted({str(r["symbol"]) for r in usable})
    results: dict[str, Any] = {}
    for symbol in symbols:
        vals = [float(r["realized_net_bps"]) for r in usable if str(r["symbol"]) != symbol]
        results[symbol] = {"n": len(vals), "mean_net_bps": _mean(vals), "median_net_bps": _median(vals)}
    return results


def paired_control_summary(
    candidate_rows: Sequence[Mapping[str, Any]],
    control_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    def key(r: Mapping[str, Any]) -> tuple[str, str, int, int]:
        return (
            str(r.get("world_state_id") or ""),
            str(r.get("symbol") or ""),
            int(r.get("timestamp_ms") or 0),
            int(r.get("horizon_seconds") or 0),
        )
    controls = {
        key(r): float(r["realized_net_bps"]) + float(r.get("realized_cost_bps") or 0.0)
        for r in control_rows
        if r.get("realized_net_bps") is not None
    }
    deltas = []
    wins = losses = ties = 0
    for row in candidate_rows:
        if row.get("realized_net_bps") is None:
            continue
        k = key(row)
        if k not in controls:
            continue
        gross = float(row["realized_net_bps"]) + float(row.get("realized_cost_bps") or 0.0)
        delta = gross - controls[k]
        deltas.append(delta)
        if delta > 0:
            wins += 1
        elif delta < 0:
            losses += 1
        else:
            ties += 1
    return {
        "paired_n": len(deltas),
        "mean_excess_gross_bps": _mean(deltas),
        "median_excess_gross_bps": _median(deltas),
        "candidate_wins": wins,
        "control_wins": losses,
        "ties": ties,
    }


def evaluate_replication_campaign(
    *,
    campaign_id: str,
    rows: Sequence[Mapping[str, Any]],
    control_rows: Sequence[Mapping[str, Any]] = (),
    contract: ReplicationContract = ReplicationContract(),
) -> dict[str, Any]:
    fills = [r for r in rows if bool(r.get("filled", False)) and r.get("realized_net_bps") is not None]
    symbols = [str(r.get("symbol") or "") for r in fills if str(r.get("symbol") or "")]
    gross = [float(r["realized_net_bps"]) + float(r.get("realized_cost_bps") or 0.0) for r in fills]
    net = [float(r["realized_net_bps"]) for r in fills]
    counts = {s: symbols.count(s) for s in set(symbols)}
    largest_symbol_n = max(counts.values(), default=0)
    largest_symbol_fraction = (largest_symbol_n / len(fills)) if fills else None
    paired = paired_control_summary(fills, control_rows)

    criteria = {
        "minimum_fills": len(fills) >= contract.minimum_fills,
        "minimum_symbols": len(set(symbols)) >= contract.minimum_symbols,
        "median_gross_positive": (_median(gross) or 0.0) > 0.0,
        "median_net_positive": (_median(net) or 0.0) > 0.0,
        "mean_excess_vs_control_positive": (
            paired["mean_excess_gross_bps"] is not None and paired["mean_excess_gross_bps"] > 0.0
        ),
        "symbol_concentration_within_limit": (
            largest_symbol_fraction is not None and largest_symbol_fraction <= contract.maximum_symbol_fraction
        ),
    }
    sample_complete = criteria["minimum_fills"] and criteria["minimum_symbols"]
    economic_pass = all(criteria.values())
    if not sample_complete:
        classification = "REPLICATION_INCOMPLETE"
    elif economic_pass:
        classification = "REPLICATION_PASS_CANDIDATE_ONLY"
    else:
        classification = "REPLICATION_FAIL_ON_TESTED_DOMAIN"

    return {
        "campaign_id": str(campaign_id),
        "classification": classification,
        "contract": asdict(contract),
        "criteria": criteria,
        "fills": len(fills),
        "symbols": len(set(symbols)),
        "worlds": len({str(r.get("world_state_id") or "") for r in fills}),
        "mean_gross_bps": _mean(gross),
        "median_gross_bps": _median(gross),
        "mean_net_bps": _mean(net),
        "median_net_bps": _median(net),
        "largest_symbol_fraction": largest_symbol_fraction,
        "paired_control": paired,
        "time_blocks": time_block_summary(fills),
        "leave_one_symbol_out": leave_one_symbol_out(fills),
        "execution_eligible": False,
        "promotion_eligible": False,
    }


def persistence_summary(campaigns: Sequence[Mapping[str, Any]], minimum_independent_campaigns: int = 2) -> dict[str, Any]:
    rows = list(campaigns)
    complete = [r for r in rows if str(r.get("classification") or "") != "REPLICATION_INCOMPLETE"]
    passes = [r for r in complete if str(r.get("classification")) == "REPLICATION_PASS_CANDIDATE_ONLY"]
    fails = [r for r in complete if str(r.get("classification")) == "REPLICATION_FAIL_ON_TESTED_DOMAIN"]

    if len(complete) < int(minimum_independent_campaigns):
        classification = "INSUFFICIENT_INDEPENDENT_CAMPAIGNS"
    elif passes and fails:
        classification = "REGIME_OR_TEMPORAL_DEPENDENCE_CANDIDATE"
    elif len(passes) == len(complete):
        classification = "PERSISTENCE_CANDIDATE_REQUIRES_FURTHER_ATTACK"
    elif len(fails) == len(complete):
        classification = "NOT_PERSISTENT_ON_TESTED_CAMPAIGNS"
    else:
        classification = "UNRESOLVED"

    return {
        "classification": classification,
        "campaigns_total": len(rows),
        "campaigns_complete": len(complete),
        "passes": len(passes),
        "fails": len(fails),
        "execution_eligible": False,
        "promotion_eligible": False,
        "authority_effect": "NONE",
    }
