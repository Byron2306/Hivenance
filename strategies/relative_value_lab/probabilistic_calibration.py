from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from statistics import mean, pstdev
from typing import Any, Deque, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


@dataclass(frozen=True)
class ProbabilityRatioState:
    schema: str
    state_id: str
    as_of_ms: int
    posterior_odds: float
    trend_mean_reversion_odds: float | None
    liquidation_asymmetry: float | None
    model_support_dissent_ratio: float | None
    iv_realized_vol_ratio: float | None
    oi_spot_volume_ratio: float | None
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("probability_ratio_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probability_ratios(
    *,
    as_of_ms: int,
    edge_positive_probability: float,
    trend_probability: float | None = None,
    mean_reversion_probability: float | None = None,
    long_liquidation_probability: float | None = None,
    short_liquidation_probability: float | None = None,
    support_weight: float | None = None,
    dissent_weight: float | None = None,
    implied_volatility: float | None = None,
    realized_volatility: float | None = None,
    open_interest: float | None = None,
    spot_volume: float | None = None,
) -> ProbabilityRatioState:
    p = _clip(edge_positive_probability, 1e-9, 1.0 - 1e-9)
    posterior_odds = p / (1.0 - p)

    def ratio(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or abs(float(b)) <= 1e-12:
            return None
        return float(a) / float(b)

    body = {
        "as_of_ms": int(as_of_ms),
        "edge_positive_probability": p,
        "trend_probability": trend_probability,
        "mean_reversion_probability": mean_reversion_probability,
        "long_liquidation_probability": long_liquidation_probability,
        "short_liquidation_probability": short_liquidation_probability,
        "support_weight": support_weight,
        "dissent_weight": dissent_weight,
        "implied_volatility": implied_volatility,
        "realized_volatility": realized_volatility,
        "open_interest": open_interest,
        "spot_volume": spot_volume,
    }
    return ProbabilityRatioState(
        schema="hivenance_probability_ratio_state_v1",
        state_id="prat_" + _digest(body).split(":", 1)[1][:24],
        as_of_ms=int(as_of_ms),
        posterior_odds=round(posterior_odds, 8),
        trend_mean_reversion_odds=None if trend_probability is None or mean_reversion_probability is None
        else round(ratio(trend_probability, mean_reversion_probability), 8),
        liquidation_asymmetry=None if long_liquidation_probability is None or short_liquidation_probability is None
        else round(ratio(long_liquidation_probability, short_liquidation_probability), 8),
        model_support_dissent_ratio=None if support_weight is None or dissent_weight is None
        else round(ratio(support_weight, dissent_weight), 8),
        iv_realized_vol_ratio=None if implied_volatility is None or realized_volatility is None
        else round(ratio(implied_volatility, realized_volatility), 8),
        oi_spot_volume_ratio=None if open_interest is None or spot_volume is None
        else round(ratio(open_interest, spot_volume), 8),
    )


@dataclass(frozen=True)
class VolatilityPosterior:
    schema: str
    state_id: str
    as_of_ms: int
    expected_volatility: float
    variance: float
    expansion_probability: float
    stress_probability: float
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.expected_volatility < 0.0 or self.variance < 0.0:
            raise ValueError("volatility_posterior_negative_moment")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("volatility_posterior_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StochasticVolatilityFilter:
    """Dependency-light EWMA stochastic-volatility state with probabilistic flags."""

    version = "hivenance.stochastic_volatility_filter.v1"

    def __init__(self, *, decay: float = 0.94, baseline_decay: float = 0.985) -> None:
        self.decay = _clip(decay)
        self.baseline_decay = _clip(baseline_decay)
        self.var = 0.0
        self.baseline_var = 0.0
        self.initialized = False

    def update(self, *, return_value: float, as_of_ms: int) -> VolatilityPosterior:
        x2 = float(return_value) ** 2
        if not self.initialized:
            self.var = x2
            self.baseline_var = x2
            self.initialized = True
        else:
            self.var = self.decay * self.var + (1.0 - self.decay) * x2
            self.baseline_var = self.baseline_decay * self.baseline_var + (1.0 - self.baseline_decay) * x2

        vol = math.sqrt(max(0.0, self.var))
        baseline = math.sqrt(max(1e-12, self.baseline_var))
        ratio = vol / baseline
        expansion_probability = _clip(0.5 + 0.5 * math.tanh((ratio - 1.0) * 2.0))
        stress_probability = _clip(0.5 + 0.5 * math.tanh((ratio - 1.35) * 2.5))

        body = {
            "as_of_ms": int(as_of_ms),
            "var": self.var,
            "baseline_var": self.baseline_var,
        }
        return VolatilityPosterior(
            schema="hivenance_volatility_posterior_v1",
            state_id="vol_" + _digest(body).split(":", 1)[1][:24],
            as_of_ms=int(as_of_ms),
            expected_volatility=round(vol, 10),
            variance=round(self.var, 12),
            expansion_probability=round(expansion_probability, 8),
            stress_probability=round(stress_probability, 8),
        )


@dataclass(frozen=True)
class ConformalInterval:
    schema: str
    interval_id: str
    as_of_ms: int
    center: float
    lower: float
    upper: float
    target_coverage: float
    empirical_coverage: float | None
    calibration_state: str
    residual_count: int
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError("conformal_interval_bounds_invalid")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("conformal_interval_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OnlineConformalCalibrator:
    """Rolling absolute-residual conformal interval for non-stationary research."""

    version = "hivenance.online_conformal_calibrator.v1"

    def __init__(self, *, window: int = 200) -> None:
        self.residuals: Deque[float] = deque(maxlen=max(10, int(window)))
        self.coverage_history: Deque[int] = deque(maxlen=max(10, int(window)))

    def observe(self, *, prediction: float, realized: float, prior_interval: tuple[float, float] | None = None) -> None:
        self.residuals.append(abs(float(realized) - float(prediction)))
        if prior_interval is not None:
            lo, hi = prior_interval
            self.coverage_history.append(1 if float(lo) <= float(realized) <= float(hi) else 0)

    def interval(self, *, prediction: float, as_of_ms: int, target_coverage: float = 0.80) -> ConformalInterval:
        target = _clip(target_coverage, 0.5, 0.999)
        values = sorted(self.residuals)
        if not values:
            radius = 0.0
        else:
            rank = min(len(values) - 1, max(0, math.ceil(target * (len(values) + 1)) - 1))
            radius = values[rank]

        empirical = None if not self.coverage_history else sum(self.coverage_history) / len(self.coverage_history)
        if empirical is None:
            state = "UNCALIBRATED"
        elif empirical < target - 0.05:
            state = "OVERCONFIDENT"
        elif empirical > target + 0.05:
            state = "UNDERCONFIDENT"
        else:
            state = "CALIBRATED"

        body = {
            "prediction": float(prediction),
            "as_of_ms": int(as_of_ms),
            "target": target,
            "radius": radius,
            "residual_count": len(values),
        }
        return ConformalInterval(
            schema="hivenance_conformal_interval_v1",
            interval_id="conf_" + _digest(body).split(":", 1)[1][:24],
            as_of_ms=int(as_of_ms),
            center=float(prediction),
            lower=round(float(prediction) - radius, 8),
            upper=round(float(prediction) + radius, 8),
            target_coverage=round(target, 6),
            empirical_coverage=None if empirical is None else round(empirical, 6),
            calibration_state=state,
            residual_count=len(values),
        )


@dataclass(frozen=True)
class CalibrationHealth:
    schema: str
    health_id: str
    sample_count: int
    brier_score: float | None
    log_loss: float | None
    calibration_error: float | None
    residual_mean: float | None
    residual_std: float | None
    feature_drift_score: float
    label_drift_score: float
    residual_drift_score: float
    overall_drift_score: float
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("calibration_health_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RollingCalibrationMonitor:
    """Tracks probability calibration and simple distribution drift diagnostics."""

    version = "hivenance.rolling_calibration_monitor.v1"

    def __init__(self, *, window: int = 200) -> None:
        size = max(20, int(window))
        self.probabilities: Deque[float] = deque(maxlen=size)
        self.labels: Deque[int] = deque(maxlen=size)
        self.residuals: Deque[float] = deque(maxlen=size)
        self.feature_scores: Deque[float] = deque(maxlen=size)

    def observe(
        self,
        *,
        probability: float,
        label: bool,
        residual: float,
        feature_score: float,
    ) -> None:
        self.probabilities.append(_clip(probability, 1e-9, 1.0 - 1e-9))
        self.labels.append(1 if label else 0)
        self.residuals.append(float(residual))
        self.feature_scores.append(float(feature_score))

    @staticmethod
    def _split_drift(values: Sequence[float]) -> float:
        if len(values) < 8:
            return 0.0
        mid = len(values) // 2
        a = list(values[:mid])
        b = list(values[mid:])
        scale = max(1e-9, pstdev(a + b), abs(mean(a)) * 0.1, 1e-6)
        return _clip(abs(mean(b) - mean(a)) / (2.0 * scale))

    def health(self) -> CalibrationHealth:
        n = len(self.labels)
        if n == 0:
            brier = log_loss = calibration_error = residual_mean = residual_std = None
        else:
            probs = list(self.probabilities)
            labels = list(self.labels)
            residuals = list(self.residuals)
            brier = mean((p - y) ** 2 for p, y in zip(probs, labels))
            log_loss = mean(-(y * math.log(p) + (1 - y) * math.log(1 - p)) for p, y in zip(probs, labels))
            calibration_error = abs(mean(probs) - mean(labels))
            residual_mean = mean(residuals)
            residual_std = pstdev(residuals) if len(residuals) >= 2 else 0.0

        feature_drift = self._split_drift(list(self.feature_scores))
        label_drift = self._split_drift(list(self.labels))
        residual_drift = self._split_drift(list(self.residuals))
        overall = max(feature_drift, label_drift, residual_drift)

        body = {
            "n": n,
            "brier": brier,
            "log_loss": log_loss,
            "calibration_error": calibration_error,
            "feature_drift": feature_drift,
            "label_drift": label_drift,
            "residual_drift": residual_drift,
        }
        return CalibrationHealth(
            schema="hivenance_calibration_health_v1",
            health_id="cal_" + _digest(body).split(":", 1)[1][:24],
            sample_count=n,
            brier_score=None if brier is None else round(brier, 8),
            log_loss=None if log_loss is None else round(log_loss, 8),
            calibration_error=None if calibration_error is None else round(calibration_error, 8),
            residual_mean=None if residual_mean is None else round(residual_mean, 8),
            residual_std=None if residual_std is None else round(residual_std, 8),
            feature_drift_score=round(feature_drift, 8),
            label_drift_score=round(label_drift, 8),
            residual_drift_score=round(residual_drift, 8),
            overall_drift_score=round(overall, 8),
        )
