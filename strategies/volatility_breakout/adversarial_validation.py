from __future__ import annotations

import hashlib
import itertools
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from statistics import NormalDist
from typing import Any, Iterable, Mapping, Sequence


_EPS = 1e-12
_EULER_GAMMA = 0.5772156649015329


def _finite(values: Iterable[Any]) -> list[float]:
    out: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _mean(values: Iterable[Any]) -> float:
    data = _finite(values)
    return statistics.fmean(data) if data else 0.0


def _median(values: Iterable[Any]) -> float:
    data = _finite(values)
    return statistics.median(data) if data else 0.0


def _stdev(values: Iterable[Any]) -> float:
    data = _finite(values)
    return statistics.stdev(data) if len(data) >= 2 else 0.0


def _percentile(values: Iterable[Any], q: float) -> float:
    data = sorted(_finite(values))
    if not data:
        return 0.0
    q = max(0.0, min(1.0, float(q)))
    index = (len(data) - 1) * q
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return data[low]
    weight = index - low
    return data[low] * (1.0 - weight) + data[high] * weight


def _skewness(values: Sequence[float]) -> float:
    if len(values) < 3:
        return 0.0
    mean = statistics.fmean(values)
    m2 = statistics.fmean((x - mean) ** 2 for x in values)
    if m2 <= _EPS:
        return 0.0
    m3 = statistics.fmean((x - mean) ** 3 for x in values)
    return m3 / (m2 ** 1.5)


def _kurtosis(values: Sequence[float]) -> float:
    """Pearson kurtosis (normal distribution == 3)."""
    if len(values) < 4:
        return 3.0
    mean = statistics.fmean(values)
    m2 = statistics.fmean((x - mean) ** 2 for x in values)
    if m2 <= _EPS:
        return 3.0
    m4 = statistics.fmean((x - mean) ** 4 for x in values)
    return m4 / (m2 ** 2)


def _trade_sharpe(values: Sequence[float]) -> float:
    """Non-annualized per-observation Sharpe used by PSR/DSR diagnostics."""
    if len(values) < 2:
        return 0.0
    std = statistics.stdev(values)
    return statistics.fmean(values) / std if std > _EPS else 0.0


def _max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def _positive_profit_concentration(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    buckets: dict[str, float] = defaultdict(float)
    for row in rows:
        profit = max(0.0, float(row.get("net_return_bps") or 0.0))
        buckets[str(row.get(key) or "UNKNOWN")] += profit
    total = sum(buckets.values())
    return max(buckets.values(), default=0.0) / total if total > _EPS else 1.0


def _month_key(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m")
    except Exception:
        return "UNKNOWN"


def _regime(row: Mapping[str, Any]) -> str:
    try:
        expansion = float(row.get("volatility_expansion"))
    except (TypeError, ValueError):
        expansion = 1.0
    try:
        stretch = abs(float(row.get("return_zscore")))
    except (TypeError, ValueError):
        stretch = 0.0
    if stretch >= 2.5 or expansion >= 2.25:
        return "SHOCK_EXPANSION"
    if stretch >= 1.25 or expansion >= 1.40:
        return "EXPANDING"
    return "QUIET"


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (float(row.get("forecast_ts") or 0.0), str(row.get("forecast_id") or "")))
    returns = _finite(row.get("net_return_bps") for row in ordered)
    if not returns:
        return {
            "samples": 0,
            "mean_net_bps": 0.0,
            "median_net_bps": 0.0,
            "win_rate": 0.0,
            "trade_sharpe": 0.0,
            "max_drawdown_bps": 0.0,
            "total_net_bps": 0.0,
        }
    return {
        "samples": len(returns),
        "mean_net_bps": round(statistics.fmean(returns), 8),
        "median_net_bps": round(statistics.median(returns), 8),
        "win_rate": round(sum(value > 0 for value in returns) / len(returns), 8),
        "trade_sharpe": round(_trade_sharpe(returns), 8),
        "max_drawdown_bps": round(_max_drawdown(returns), 8),
        "total_net_bps": round(sum(returns), 8),
        "worst_trade_bps": round(min(returns), 8),
        "best_trade_bps": round(max(returns), 8),
    }


def _block_bootstrap_mean_ci(
    rows: Sequence[Mapping[str, Any]],
    *,
    samples: int,
    block_size: int,
    seed: int,
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (float(row.get("forecast_ts") or 0.0), str(row.get("forecast_id") or "")))
    returns = _finite(row.get("net_return_bps") for row in ordered)
    n = len(returns)
    if n < 2:
        return {"samples": n, "bootstrap_samples": 0, "lower_95_bps": 0.0, "upper_95_bps": 0.0}
    rng = random.Random(seed)
    block = max(1, min(int(block_size), n))
    draws: list[float] = []
    max_start = max(0, n - block)
    for _ in range(max(1, int(samples))):
        synthetic: list[float] = []
        while len(synthetic) < n:
            start = rng.randint(0, max_start) if max_start else 0
            synthetic.extend(returns[start:start + block])
        draws.append(statistics.fmean(synthetic[:n]))
    return {
        "samples": n,
        "bootstrap_samples": len(draws),
        "block_size": block,
        "mean_bps": round(statistics.fmean(returns), 8),
        "lower_95_bps": round(_percentile(draws, 0.025), 8),
        "upper_95_bps": round(_percentile(draws, 0.975), 8),
        "probability_mean_positive": round(sum(value > 0 for value in draws) / len(draws), 8),
    }


def _purged_walk_forward(
    rows: Sequence[Mapping[str, Any]],
    *,
    folds: int,
    purge_seconds: int,
    embargo_seconds: int,
) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (float(row.get("forecast_ts") or 0.0), str(row.get("forecast_id") or "")))
    n = len(ordered)
    folds = max(2, min(int(folds), max(2, n // 4))) if n >= 8 else 0
    if not folds:
        return []
    boundaries = [round(i * n / folds) for i in range(folds + 1)]
    results: list[dict[str, Any]] = []
    for fold_index in range(1, folds):
        test_start_index = boundaries[fold_index]
        test_end_index = boundaries[fold_index + 1]
        test = ordered[test_start_index:test_end_index]
        if not test:
            continue
        test_start = min(float(row.get("forecast_ts") or 0.0) for row in test)
        test_end = max(float(row.get("target_ts") or row.get("forecast_ts") or 0.0) for row in test)
        # Walk-forward uses only earlier observations. Purging removes labels whose
        # outcome interval overlaps the test boundary. Embargo is recorded and
        # applied to any future extension, although no future rows are admitted here.
        train = [
            row for row in ordered[:test_start_index]
            if float(row.get("target_ts") or row.get("forecast_ts") or 0.0) < test_start - purge_seconds
        ]
        embargo_until = test_end + embargo_seconds
        train_metrics = _metrics(train)
        test_metrics = _metrics(test)
        results.append({
            "fold_index": fold_index,
            "train_start_ts": min((float(row.get("forecast_ts") or 0.0) for row in train), default=0.0),
            "train_end_ts": max((float(row.get("target_ts") or 0.0) for row in train), default=0.0),
            "test_start_ts": test_start,
            "test_end_ts": test_end,
            "embargo_until_ts": embargo_until,
            "purge_seconds": int(purge_seconds),
            "embargo_seconds": int(embargo_seconds),
            "train": train_metrics,
            "test": test_metrics,
            "test_positive": bool(test_metrics.get("mean_net_bps", 0.0) > 0),
        })
    return results


def _holdouts(rows: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    values = sorted({str(row.get(key) or "UNKNOWN") for row in rows})
    out: list[dict[str, Any]] = []
    for value in values:
        test = [row for row in rows if str(row.get(key) or "UNKNOWN") == value]
        train = [row for row in rows if str(row.get(key) or "UNKNOWN") != value]
        out.append({
            "holdout_type": key,
            "holdout_value": value,
            "train": _metrics(train),
            "test": _metrics(test),
            "test_positive": _mean(row.get("net_return_bps") for row in test) > 0,
        })
    return out


def _parameter_neighbourhood(
    rows: Sequence[Mapping[str, Any]],
    *,
    base_probability: float,
    base_expected_net_bps: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for probability_shift, net_shift in itertools.product((-0.05, 0.0, 0.05), (-10.0, 0.0, 10.0)):
        probability_gate = max(0.0, min(1.0, base_probability + probability_shift))
        edge_gate = base_expected_net_bps + net_shift
        selected = [
            row for row in rows
            if float(row.get("probability_positive_net") or 0.0) >= probability_gate
            and float(row.get("expected_net_bps") or 0.0) >= edge_gate
        ]
        metrics = _metrics(selected)
        out.append({
            "probability_gate": round(probability_gate, 6),
            "expected_net_gate_bps": round(edge_gate, 6),
            "probability_shift": probability_shift,
            "expected_net_shift_bps": net_shift,
            "selected_samples": len(selected),
            "metrics": metrics,
            "positive": bool(metrics.get("samples", 0) and metrics.get("mean_net_bps", 0.0) > 0),
        })
    return out


def _deflated_sharpe_probability(
    returns: Sequence[float],
    *,
    trial_sharpes: Sequence[float],
) -> dict[str, Any]:
    values = _finite(returns)
    trials = _finite(trial_sharpes)
    n = len(values)
    if n < 3:
        return {
            "samples": n,
            "observed_sharpe": 0.0,
            "expected_max_noise_sharpe": 0.0,
            "dsr_probability": 0.0,
            "status": "INSUFFICIENT_SAMPLES",
        }
    observed = _trade_sharpe(values)
    number_trials = max(1, len(trials))
    variance_trials = statistics.pvariance(trials) if len(trials) >= 2 else 0.0
    if number_trials <= 1 or variance_trials <= _EPS:
        expected_max = 0.0
    else:
        normal = NormalDist()
        q1 = normal.inv_cdf(max(_EPS, min(1.0 - _EPS, 1.0 - 1.0 / number_trials)))
        q2 = normal.inv_cdf(max(_EPS, min(1.0 - _EPS, 1.0 - 1.0 / (number_trials * math.e))))
        expected_max = math.sqrt(variance_trials) * ((1.0 - _EULER_GAMMA) * q1 + _EULER_GAMMA * q2)
    skew = _skewness(values)
    kurt = _kurtosis(values)
    denominator_term = 1.0 - skew * expected_max + ((kurt - 1.0) / 4.0) * (expected_max ** 2)
    denominator = math.sqrt(max(_EPS, denominator_term))
    statistic = (observed - expected_max) * math.sqrt(max(1, n - 1)) / denominator
    probability = NormalDist().cdf(statistic)
    return {
        "samples": n,
        "number_of_trials": number_trials,
        "observed_sharpe": round(observed, 8),
        "trial_sharpe_variance": round(variance_trials, 8),
        "expected_max_noise_sharpe": round(expected_max, 8),
        "skewness": round(skew, 8),
        "pearson_kurtosis": round(kurt, 8),
        "test_statistic": round(statistic, 8),
        "dsr_probability": round(probability, 8),
        "status": "OK",
    }


def estimate_cscv_pbo(
    candidate_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    slices: int = 8,
    max_combinations: int = 252,
) -> dict[str, Any]:
    """CSCV-style Probability of Backtest Overfitting estimate.

    The implementation uses contiguous chronological slices, evaluates candidate
    strategy configurations on symmetric in-sample/out-of-sample partitions,
    selects the highest in-sample Sharpe, and records its out-of-sample relative
    rank. It is intentionally labeled an estimate because sparse real-world
    candidate matrices may not satisfy the ideal balanced CSCV assumptions.
    """
    candidates = sorted(candidate_rows)
    if len(candidates) < 2:
        return {"status": "INSUFFICIENT_CANDIDATES", "pbo_estimate": 1.0, "combinations": 0}
    all_times = sorted({
        float(row.get("forecast_ts") or 0.0)
        for rows in candidate_rows.values() for row in rows
    })
    slices = max(4, int(slices))
    if len(all_times) < slices * 2:
        return {"status": "INSUFFICIENT_TIME_SLICES", "pbo_estimate": 1.0, "combinations": 0}
    boundaries = [round(i * len(all_times) / slices) for i in range(slices + 1)]
    time_slices = [all_times[boundaries[i]:boundaries[i + 1]] for i in range(slices)]
    half = slices // 2
    combinations = list(itertools.combinations(range(slices), half))
    if len(combinations) > max_combinations:
        step = max(1, len(combinations) // max_combinations)
        combinations = combinations[::step][:max_combinations]

    logits: list[float] = []
    selections: list[dict[str, Any]] = []
    for selected_slices in combinations:
        train_slice_set = set(selected_slices)
        train_times = {ts for index, values in enumerate(time_slices) if index in train_slice_set for ts in values}
        test_times = {ts for index, values in enumerate(time_slices) if index not in train_slice_set for ts in values}
        train_scores: dict[str, float] = {}
        test_scores: dict[str, float] = {}
        for candidate in candidates:
            train_returns = _finite(
                row.get("net_return_bps") for row in candidate_rows[candidate]
                if float(row.get("forecast_ts") or 0.0) in train_times
            )
            test_returns = _finite(
                row.get("net_return_bps") for row in candidate_rows[candidate]
                if float(row.get("forecast_ts") or 0.0) in test_times
            )
            if len(train_returns) < 2 or len(test_returns) < 2:
                continue
            train_scores[candidate] = _trade_sharpe(train_returns)
            test_scores[candidate] = _trade_sharpe(test_returns)
        common = sorted(set(train_scores) & set(test_scores))
        if len(common) < 2:
            continue
        selected = max(common, key=lambda key: (train_scores[key], key))
        ranked = sorted(common, key=lambda key: (test_scores[key], key))
        rank_index = ranked.index(selected) + 1
        relative_rank = rank_index / (len(ranked) + 1.0)
        relative_rank = max(_EPS, min(1.0 - _EPS, relative_rank))
        logit = math.log(relative_rank / (1.0 - relative_rank))
        logits.append(logit)
        selections.append({
            "selected_candidate": selected,
            "train_sharpe": round(train_scores[selected], 8),
            "test_sharpe": round(test_scores[selected], 8),
            "oos_relative_rank": round(relative_rank, 8),
            "logit": round(logit, 8),
        })
    if not logits:
        return {"status": "INSUFFICIENT_BALANCED_SPLITS", "pbo_estimate": 1.0, "combinations": 0}
    return {
        "status": "OK",
        "method": "CSCV_STYLE_CONTIGUOUS_SLICES",
        "candidate_count": len(candidates),
        "time_slices": slices,
        "combinations": len(logits),
        "pbo_estimate": round(sum(value <= 0.0 for value in logits) / len(logits), 8),
        "median_logit": round(statistics.median(logits), 8),
        "selections": selections[:100],
    }


class AdversarialValidator:
    version = "phase4.adversarial.v1"

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self.min_candidate_trades = max(1, int(getattr(cfg, "phase4_min_candidate_trades", 100) or 100))
        self.min_distinct_days = max(1, int(getattr(cfg, "phase4_min_distinct_days", 14) or 14))
        self.walk_forward_folds = max(3, int(getattr(cfg, "phase4_walk_forward_folds", 5) or 5))
        self.purge_seconds = max(0, int(getattr(cfg, "phase4_purge_seconds", 3600) or 3600))
        self.embargo_seconds = max(0, int(getattr(cfg, "phase4_embargo_seconds", 3600) or 3600))
        self.bootstrap_samples = max(100, int(getattr(cfg, "phase4_bootstrap_samples", 1000) or 1000))
        self.bootstrap_block_size = max(1, int(getattr(cfg, "phase4_bootstrap_block_size", 5) or 5))
        self.dsr_min_probability = float(getattr(cfg, "phase4_dsr_min_probability", 0.95) or 0.95)
        self.pbo_max = float(getattr(cfg, "phase4_pbo_max", 0.20) or 0.20)
        self.min_walk_forward_positive_ratio = float(getattr(cfg, "phase4_min_walk_forward_positive_ratio", 0.60) or 0.60)
        self.min_parameter_positive_ratio = float(getattr(cfg, "phase4_min_parameter_positive_ratio", 0.70) or 0.70)
        self.max_symbol_profit_concentration = float(getattr(cfg, "phase4_max_symbol_profit_concentration", 0.25) or 0.25)
        self.max_month_profit_concentration = float(getattr(cfg, "phase4_max_month_profit_concentration", 0.35) or 0.35)
        self.max_cost2_loss_bps = float(getattr(cfg, "phase4_max_cost2_loss_bps", 50.0) or 50.0)
        self.selection_min_probability = float(getattr(cfg, "phase4_selection_min_probability", 0.50) or 0.50)
        self.selection_min_expected_net_bps = float(getattr(cfg, "phase4_selection_min_expected_net_bps", 0.0) or 0.0)

    @staticmethod
    def _candidate_key(row: Mapping[str, Any]) -> str:
        return f"{row.get('model_id')}::{row.get('order_policy')}"

    def validate(self, rows: Sequence[Mapping[str, Any]], *, run_id: str) -> dict[str, Any]:
        clean = [dict(row) for row in rows if row.get("status") == "COMPLETED"]
        primary = [row for row in clean if not str(row.get("model_id") or "").startswith("baseline_")]
        normal = [row for row in clean if row.get("scenario") == "normal"]
        normal_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in normal:
            normal_by_candidate[self._candidate_key(row)].append(row)
        all_trial_sharpes = [
            _trade_sharpe(_finite(row.get("net_return_bps") for row in candidate_rows))
            for candidate_rows in normal_by_candidate.values()
            if len(candidate_rows) >= 2
        ]
        pbo = estimate_cscv_pbo(normal_by_candidate, slices=8)

        candidate_results: list[dict[str, Any]] = []
        fold_results: list[dict[str, Any]] = []
        holdout_results: list[dict[str, Any]] = []
        perturbation_results: list[dict[str, Any]] = []
        for candidate_key, candidate_normal in sorted(normal_by_candidate.items()):
            model_id, order_policy = candidate_key.split("::", 1)
            if model_id.startswith("baseline_"):
                continue
            candidate_all = [
                row for row in primary
                if row.get("model_id") == model_id and row.get("order_policy") == order_policy
            ]
            scenarios = {
                scenario: _metrics([row for row in candidate_all if row.get("scenario") == scenario])
                for scenario in sorted({str(row.get("scenario") or "") for row in candidate_all})
            }
            folds = _purged_walk_forward(
                candidate_normal,
                folds=self.walk_forward_folds,
                purge_seconds=self.purge_seconds,
                embargo_seconds=self.embargo_seconds,
            )
            symbol_holdouts = _holdouts(candidate_normal, "symbol")
            regime_rows = [dict(row, regime=_regime(row)) for row in candidate_normal]
            regime_holdouts = _holdouts(regime_rows, "regime")
            perturbations = _parameter_neighbourhood(
                candidate_normal,
                base_probability=self.selection_min_probability,
                base_expected_net_bps=self.selection_min_expected_net_bps,
            )
            returns = _finite(row.get("net_return_bps") for row in candidate_normal)
            seed = int(hashlib.sha256(f"{run_id}:{candidate_key}".encode()).hexdigest()[:16], 16)
            bootstrap = _block_bootstrap_mean_ci(
                candidate_normal,
                samples=self.bootstrap_samples,
                block_size=self.bootstrap_block_size,
                seed=seed,
            )
            dsr = _deflated_sharpe_probability(returns, trial_sharpes=all_trial_sharpes)
            distinct_days = len({datetime.fromtimestamp(float(row.get("forecast_ts") or 0.0), timezone.utc).date() for row in candidate_normal})
            symbol_concentration = _positive_profit_concentration(candidate_normal, "symbol")
            month_rows = [dict(row, month=_month_key(float(row.get("forecast_ts") or 0.0))) for row in candidate_normal]
            month_concentration = _positive_profit_concentration(month_rows, "month")
            walk_positive_ratio = (
                sum(1 for fold in folds if fold.get("test_positive")) / len(folds)
                if folds else 0.0
            )
            parameter_positive_ratio = (
                sum(1 for item in perturbations if item.get("positive")) / len(perturbations)
                if perturbations else 0.0
            )
            symbol_positive_ratio = (
                sum(1 for item in symbol_holdouts if item.get("test_positive")) / len(symbol_holdouts)
                if symbol_holdouts else 0.0
            )
            regime_positive_ratio = (
                sum(1 for item in regime_holdouts if item.get("test_positive")) / len(regime_holdouts)
                if regime_holdouts else 0.0
            )
            reasons: list[str] = []
            if len(candidate_normal) < self.min_candidate_trades:
                reasons.append("insufficient_normal_completed_trades")
            if distinct_days < self.min_distinct_days:
                reasons.append("insufficient_distinct_days")
            if bootstrap.get("lower_95_bps", 0.0) <= 0:
                reasons.append("bootstrap_lower_bound_not_positive")
            if walk_positive_ratio < self.min_walk_forward_positive_ratio:
                reasons.append("walk_forward_instability")
            if parameter_positive_ratio < self.min_parameter_positive_ratio:
                reasons.append("selection_threshold_instability")
            if symbol_concentration > self.max_symbol_profit_concentration:
                reasons.append("symbol_profit_concentration")
            if month_concentration > self.max_month_profit_concentration:
                reasons.append("month_profit_concentration")
            if dsr.get("dsr_probability", 0.0) < self.dsr_min_probability:
                reasons.append("deflated_sharpe_below_gate")
            if scenarios.get("cost_1_5x", {}).get("mean_net_bps", 0.0) <= 0:
                reasons.append("negative_at_1_5x_cost")
            if scenarios.get("cost_2x", {}).get("mean_net_bps", 0.0) < -self.max_cost2_loss_bps:
                reasons.append("catastrophic_at_2x_cost")
            if symbol_positive_ratio < 0.50:
                reasons.append("symbol_holdout_instability")
            if regime_positive_ratio < 0.50:
                reasons.append("regime_holdout_instability")

            base_metrics = _metrics(candidate_normal)
            robust_score = (
                float(bootstrap.get("lower_95_bps", 0.0))
                + 10.0 * walk_positive_ratio
                + 5.0 * parameter_positive_ratio
                + 5.0 * symbol_positive_ratio
                + 5.0 * regime_positive_ratio
                + 10.0 * float(dsr.get("dsr_probability", 0.0))
                - 10.0 * symbol_concentration
                - 10.0 * month_concentration
            )
            result = {
                "candidate_key": candidate_key,
                "model_id": model_id,
                "order_policy": order_policy,
                "normal": base_metrics,
                "scenarios": scenarios,
                "distinct_days": distinct_days,
                "distinct_symbols": len({str(row.get("symbol") or "") for row in candidate_normal}),
                "bootstrap": bootstrap,
                "deflated_sharpe": dsr,
                "walk_forward_positive_ratio": round(walk_positive_ratio, 8),
                "parameter_positive_ratio": round(parameter_positive_ratio, 8),
                "symbol_holdout_positive_ratio": round(symbol_positive_ratio, 8),
                "regime_holdout_positive_ratio": round(regime_positive_ratio, 8),
                "symbol_profit_concentration": round(symbol_concentration, 8),
                "month_profit_concentration": round(month_concentration, 8),
                "robust_score": round(robust_score, 8),
                "passes_candidate_gates": not reasons,
                "reasons": reasons,
                "execution_eligible": False,
                "real_orders_submitted": 0,
            }
            candidate_results.append(result)
            fold_results.extend(dict(item, candidate_key=candidate_key) for item in folds)
            holdout_results.extend(dict(item, candidate_key=candidate_key) for item in symbol_holdouts)
            holdout_results.extend(dict(item, candidate_key=candidate_key) for item in regime_holdouts)
            perturbation_results.extend(dict(item, candidate_key=candidate_key) for item in perturbations)

        champion = max(candidate_results, key=lambda item: (item.get("robust_score", -math.inf), item.get("candidate_key", "")), default=None)
        pbo_value = float(pbo.get("pbo_estimate", 1.0))
        global_reasons: list[str] = []
        if not candidate_results:
            global_reasons.append("no_primary_candidates")
        if pbo_value > self.pbo_max:
            global_reasons.append("probability_of_backtest_overfitting_above_gate")
        if not champion or not champion.get("passes_candidate_gates"):
            global_reasons.append("no_candidate_passed_all_adversarial_gates")
        if any(bool(row.get("execution_wired")) for row in clean):
            global_reasons.append("execution_wiring_violation")
        if sum(int(row.get("real_orders_submitted") or 0) for row in clean):
            global_reasons.append("real_order_submission_violation")
        ready = not global_reasons
        return {
            "phase": 4,
            "mode": "adversarial_validation_only",
            "validator_version": self.version,
            "run_id": run_id,
            "status": "HEALTHY" if clean else "WAITING_FOR_PHASE3_EVIDENCE",
            "rows_examined": len(clean),
            "primary_rows": len(primary),
            "candidate_count": len(candidate_results),
            "pbo": pbo,
            "champion": champion,
            "candidate_results": candidate_results,
            "fold_results": fold_results,
            "holdout_results": holdout_results,
            "perturbation_results": perturbation_results,
            "readiness": {
                "phase": 4,
                "ready_for_phase5_review": ready,
                "execution_eligible": False,
                "human_review_required": True,
                "real_orders_submitted": 0,
                "reasons": global_reasons,
            },
            "execution_wired": False,
            "real_orders_submitted": 0,
        }
