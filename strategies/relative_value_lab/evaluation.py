from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .dataset import RelativeValueExample


FEATURE_NAMES = (
    "spread_zscore",
    "relationship_stability",
    "half_life_log",
    "relative_return_1step_bps",
    "relative_return_3step_bps",
    "relative_return_6step_bps",
    "pair_spread_cost_bps_proxy",
    "quote_ofi_delta",
    "aggressor_flow_delta",
    "book_imbalance_delta",
    "depth_recovery_delta",
    "trade_intensity_log",
)


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def _feature_values(example: RelativeValueExample) -> list[Optional[float]]:
    half_life = _finite(example.half_life_seconds)
    intensity = _finite(example.trade_intensity_sum)
    return [
        _finite(example.spread_zscore),
        _finite(example.relationship_stability),
        None if half_life is None else math.log1p(max(0.0, half_life)),
        _finite(example.relative_return_1step_bps),
        _finite(example.relative_return_3step_bps),
        _finite(example.relative_return_6step_bps),
        _finite(example.pair_spread_cost_bps_proxy),
        _finite(example.quote_ofi_delta),
        _finite(example.aggressor_flow_delta),
        _finite(example.book_imbalance_delta),
        _finite(example.depth_recovery_delta),
        None if intensity is None else math.log1p(max(0.0, intensity)),
    ]


def _solve(matrix: list[list[float]], vector: list[float]) -> Optional[list[float]]:
    n = len(vector)
    a = [list(row) + [float(vector[i])] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
        divisor = a[col][col]
        a[col] = [value / divisor for value in a[col]]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if factor == 0:
                continue
            a[row] = [
                current - factor * reference
                for current, reference in zip(a[row], a[col])
            ]
    return [a[row][-1] for row in range(n)]


@dataclass(frozen=True)
class RidgeFit:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    imputes: tuple[float, ...]
    coefficients: tuple[float, ...]
    target_mean: float
    samples: int

    def predict(self, example: RelativeValueExample) -> float:
        values = _feature_values(example)
        normalized = []
        for value, impute, mean, scale in zip(values, self.imputes, self.means, self.scales):
            raw = impute if value is None else value
            normalized.append((raw - mean) / scale)
        return self.target_mean + sum(
            coefficient * value
            for coefficient, value in zip(self.coefficients, normalized)
        )


class ExpandingRidgeModel:
    model_id = "relative_value_expanding_ridge_v1"

    def __init__(self, *, ridge_alpha: float = 8.0, minimum_train_samples: int = 80) -> None:
        self.ridge_alpha = max(1e-9, float(ridge_alpha))
        self.minimum_train_samples = max(len(FEATURE_NAMES) + 5, int(minimum_train_samples))

    def fit(
        self,
        examples: Sequence[RelativeValueExample],
        *,
        horizon_seconds: int,
        cutoff_timestamp_ms: int,
    ) -> Optional[RidgeFit]:
        key = f"{int(horizon_seconds)}s"
        eligible: list[tuple[RelativeValueExample, float]] = []
        for example in examples:
            label = _finite(example.labels_bps.get(key))
            label_ts = example.label_timestamps_ms.get(key)
            if label is None or label_ts is None:
                continue
            # Critical leakage rule: a label enters training only after it would
            # have been observable in real time.
            if int(label_ts) > int(cutoff_timestamp_ms):
                continue
            eligible.append((example, label))
        if len(eligible) < self.minimum_train_samples:
            return None

        raw_columns = list(zip(*[_feature_values(example) for example, _ in eligible]))
        imputes: list[float] = []
        means: list[float] = []
        scales: list[float] = []
        for column in raw_columns:
            observed = [float(value) for value in column if value is not None]
            impute = _median(observed)
            completed = [impute if value is None else float(value) for value in column]
            mean = statistics.fmean(completed)
            scale = statistics.pstdev(completed) if len(completed) > 1 else 0.0
            if not math.isfinite(scale) or scale < 1e-9:
                scale = 1.0
            imputes.append(impute)
            means.append(mean)
            scales.append(scale)

        x: list[list[float]] = []
        y = [label for _, label in eligible]
        y_mean = statistics.fmean(y)
        centered_y = [value - y_mean for value in y]
        for example, _ in eligible:
            row = []
            for value, impute, mean, scale in zip(
                _feature_values(example), imputes, means, scales
            ):
                raw = impute if value is None else float(value)
                row.append((raw - mean) / scale)
            x.append(row)

        p = len(FEATURE_NAMES)
        xtx = [[0.0 for _ in range(p)] for _ in range(p)]
        xty = [0.0 for _ in range(p)]
        for row, target in zip(x, centered_y):
            for i in range(p):
                xty[i] += row[i] * target
                for j in range(p):
                    xtx[i][j] += row[i] * row[j]
        for i in range(p):
            xtx[i][i] += self.ridge_alpha

        coefficients = _solve(xtx, xty)
        if coefficients is None:
            return None
        return RidgeFit(
            means=tuple(means),
            scales=tuple(scales),
            imputes=tuple(imputes),
            coefficients=tuple(coefficients),
            target_mean=y_mean,
            samples=len(eligible),
        )


@dataclass(frozen=True)
class WalkForwardPrediction:
    schema: str
    example_id: str
    pair_id: str
    timestamp_ms: int
    horizon_seconds: int
    model_id: str
    predicted_signed_bps: float
    realized_signed_bps: float
    directional_gross_bps: Optional[float]
    spread_cost_proxy_bps: Optional[float]
    directional_after_spread_proxy_bps: Optional[float]
    train_samples: int
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelMetrics:
    model_id: str
    horizon_seconds: int
    samples: int
    mean_prediction_bps: Optional[float]
    mean_realized_bps: Optional[float]
    mae_bps: Optional[float]
    rmse_bps: Optional[float]
    sign_accuracy: Optional[float]
    mean_directional_gross_bps: Optional[float]
    mean_directional_after_spread_proxy_bps: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RelativeValueWalkForwardEvaluator:
    """Outcome-lag-aware walk-forward evaluation for pair-relative forecasts."""

    BASELINE_IDS = (
        "baseline_zero_v1",
        "baseline_continuation_v1",
        "baseline_reversal_v1",
        "relative_value_ou_mean_reversion_v1",
    )

    def __init__(
        self,
        *,
        horizons_seconds: Sequence[int] = (10, 30, 60, 120),
        ridge_alpha: float = 8.0,
        minimum_train_samples: int = 80,
    ) -> None:
        self.horizons_seconds = tuple(sorted({max(1, int(h)) for h in horizons_seconds}))
        self.ridge = ExpandingRidgeModel(
            ridge_alpha=ridge_alpha,
            minimum_train_samples=minimum_train_samples,
        )

    @staticmethod
    def _ou_prediction(example: RelativeValueExample, horizon: int) -> Optional[float]:
        current = _finite(example.spread)
        equilibrium = _finite(example.ou_equilibrium)
        kappa = _finite(example.mean_reversion_speed_per_sec)
        if current is None or equilibrium is None or kappa is None or kappa < 0:
            return None
        future = equilibrium + (current - equilibrium) * math.exp(-kappa * horizon)
        return (future - current) * 10_000.0

    @staticmethod
    def _baseline_prediction(
        example: RelativeValueExample,
        *,
        model_id: str,
        horizon_seconds: int,
    ) -> Optional[float]:
        if model_id == "baseline_zero_v1":
            return 0.0
        one_step = _finite(example.relative_return_1step_bps)
        if one_step is None:
            return None
        ratio = max(1.0, horizon_seconds / max(1e-9, example.sample_interval_sec))
        scaled = one_step * math.sqrt(ratio)
        if model_id == "baseline_continuation_v1":
            return scaled
        if model_id == "baseline_reversal_v1":
            return -scaled
        if model_id == "relative_value_ou_mean_reversion_v1":
            return RelativeValueWalkForwardEvaluator._ou_prediction(example, horizon_seconds)
        return None

    @staticmethod
    def _prediction_row(
        *,
        example: RelativeValueExample,
        horizon: int,
        model_id: str,
        prediction: float,
        realized: float,
        train_samples: int = 0,
    ) -> WalkForwardPrediction:
        sign = 1.0 if prediction > 0 else -1.0 if prediction < 0 else 0.0
        directional = None if sign == 0.0 else sign * realized
        cost = _finite(example.pair_spread_cost_bps_proxy)
        after_cost = None
        if directional is not None and cost is not None:
            after_cost = directional - cost
        return WalkForwardPrediction(
            schema="hivenance_relative_value_walk_forward_prediction_v1",
            example_id=example.example_id,
            pair_id=example.pair_id,
            timestamp_ms=example.timestamp_ms,
            horizon_seconds=horizon,
            model_id=model_id,
            predicted_signed_bps=prediction,
            realized_signed_bps=realized,
            directional_gross_bps=directional,
            spread_cost_proxy_bps=cost,
            directional_after_spread_proxy_bps=after_cost,
            train_samples=int(train_samples),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
        )

    def evaluate(
        self,
        examples: Iterable[RelativeValueExample],
    ) -> tuple[list[WalkForwardPrediction], list[ModelMetrics]]:
        ordered = sorted(examples, key=lambda item: (item.timestamp_ms, item.pair_id))
        predictions: list[WalkForwardPrediction] = []

        for horizon in self.horizons_seconds:
            key = f"{horizon}s"
            ridge_history: list[RelativeValueExample] = []
            cached_cutoff: Optional[int] = None
            cached_fit: Optional[RidgeFit] = None

            for example in ordered:
                realized = _finite(example.labels_bps.get(key))
                label_ts = example.label_timestamps_ms.get(key)
                if realized is None or label_ts is None:
                    ridge_history.append(example)
                    continue

                for model_id in self.BASELINE_IDS:
                    predicted = self._baseline_prediction(
                        example,
                        model_id=model_id,
                        horizon_seconds=horizon,
                    )
                    if predicted is None:
                        continue
                    predictions.append(self._prediction_row(
                        example=example,
                        horizon=horizon,
                        model_id=model_id,
                        prediction=predicted,
                        realized=realized,
                    ))

                # Refit only when the timestamp advances. All pairs observed at
                # the same timestamp see exactly the same historical label set.
                if cached_cutoff != example.timestamp_ms:
                    cached_fit = self.ridge.fit(
                        ridge_history,
                        horizon_seconds=horizon,
                        cutoff_timestamp_ms=example.timestamp_ms,
                    )
                    cached_cutoff = example.timestamp_ms
                if cached_fit is not None:
                    predicted = cached_fit.predict(example)
                    predictions.append(self._prediction_row(
                        example=example,
                        horizon=horizon,
                        model_id=self.ridge.model_id,
                        prediction=predicted,
                        realized=realized,
                        train_samples=cached_fit.samples,
                    ))

                ridge_history.append(example)

        metrics = self.summarize(predictions)
        return predictions, metrics

    @staticmethod
    def summarize(predictions: Sequence[WalkForwardPrediction]) -> list[ModelMetrics]:
        groups: dict[tuple[str, int], list[WalkForwardPrediction]] = {}
        for row in predictions:
            groups.setdefault((row.model_id, row.horizon_seconds), []).append(row)

        output: list[ModelMetrics] = []
        for (model_id, horizon), rows in sorted(groups.items()):
            predicted = [row.predicted_signed_bps for row in rows]
            realized = [row.realized_signed_bps for row in rows]
            errors = [p - r for p, r in zip(predicted, realized)]
            nonzero = [row for row in rows if row.predicted_signed_bps != 0.0]
            correct = sum(
                1 for row in nonzero
                if (row.predicted_signed_bps > 0) == (row.realized_signed_bps > 0)
            )
            gross = [
                float(row.directional_gross_bps)
                for row in rows
                if row.directional_gross_bps is not None
            ]
            net = [
                float(row.directional_after_spread_proxy_bps)
                for row in rows
                if row.directional_after_spread_proxy_bps is not None
            ]
            output.append(ModelMetrics(
                model_id=model_id,
                horizon_seconds=horizon,
                samples=len(rows),
                mean_prediction_bps=statistics.fmean(predicted) if predicted else None,
                mean_realized_bps=statistics.fmean(realized) if realized else None,
                mae_bps=statistics.fmean(abs(value) for value in errors) if errors else None,
                rmse_bps=math.sqrt(statistics.fmean(value * value for value in errors)) if errors else None,
                sign_accuracy=(correct / len(nonzero)) if nonzero else None,
                mean_directional_gross_bps=statistics.fmean(gross) if gross else None,
                mean_directional_after_spread_proxy_bps=statistics.fmean(net) if net else None,
            ))
        return output
