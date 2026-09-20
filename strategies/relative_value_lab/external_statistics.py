from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .statistical_synthesis import StatisticalEvidence


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ExternalMetricObservation:
    schema: str
    observation_id: str
    metric: str
    provider: str
    symbol_scope: str
    observed_at_ms: int
    available_at_ms: int
    value: float
    unit: str
    source_locator: str
    source_digest: str
    revision_policy: str
    metadata: Mapping[str, Any]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.schema != "hivenance_external_metric_observation_v1":
            raise ValueError("external_metric_schema_invalid")
        if int(self.available_at_ms) < int(self.observed_at_ms):
            raise ValueError("external_metric_available_before_observation")
        if not str(self.source_digest).startswith("sha256:"):
            raise ValueError("external_metric_source_digest_unbound")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("external_metric_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ExternalMetricFeature:
    schema: str
    feature_id: str
    metric: str
    symbol_scope: str
    as_of_ms: int
    observation_id: str
    value: float
    delta: float | None
    velocity: float | None
    zscore: float | None
    percentile: float | None
    ratio: float | None
    ratio_name: str | None
    evidence_root: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if int(self.as_of_ms) <= 0:
            raise ValueError("external_metric_feature_asof_invalid")
        if not str(self.evidence_root).startswith("sha256:"):
            raise ValueError("external_metric_feature_root_unbound")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("external_metric_feature_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExternalStatisticsSensorium:
    """Timestamped external-telemetry memory and deterministic normalizer."""

    version = "hivenance.external_statistics_sensorium.v1"

    def __init__(self) -> None:
        self._rows: list[ExternalMetricObservation] = []

    def observe(
        self,
        *,
        metric: str,
        provider: str,
        symbol_scope: str,
        observed_at_ms: int,
        available_at_ms: int,
        value: float,
        unit: str,
        source_locator: str,
        source_bytes_or_value: Any,
        revision_policy: str = "UNKNOWN",
        metadata: Mapping[str, Any] | None = None,
    ) -> ExternalMetricObservation:
        source_digest = _digest(source_bytes_or_value)
        body = {
            "metric": str(metric),
            "provider": str(provider),
            "symbol_scope": str(symbol_scope),
            "observed_at_ms": int(observed_at_ms),
            "available_at_ms": int(available_at_ms),
            "value": float(value),
            "unit": str(unit),
            "source_locator": str(source_locator),
            "source_digest": source_digest,
            "revision_policy": str(revision_policy),
            "metadata": dict(metadata or {}),
        }
        row = ExternalMetricObservation(
            schema="hivenance_external_metric_observation_v1",
            observation_id="ext_" + _digest(body).split(":", 1)[1][:24],
            metric=str(metric),
            provider=str(provider),
            symbol_scope=str(symbol_scope),
            observed_at_ms=int(observed_at_ms),
            available_at_ms=int(available_at_ms),
            value=float(value),
            unit=str(unit),
            source_locator=str(source_locator),
            source_digest=source_digest,
            revision_policy=str(revision_policy),
            metadata=dict(metadata or {}),
        )
        self._rows.append(row)
        return row

    def _eligible(self, metric: str, symbol_scope: str, as_of_ms: int) -> list[ExternalMetricObservation]:
        rows = [
            row for row in self._rows
            if row.metric == str(metric)
            and row.symbol_scope == str(symbol_scope)
            and int(row.available_at_ms) < int(as_of_ms)
        ]
        return sorted(rows, key=lambda row: (row.available_at_ms, row.observation_id))

    def feature(
        self,
        *,
        metric: str,
        symbol_scope: str,
        as_of_ms: int,
        ratio_metric: str | None = None,
        window: int = 20,
    ) -> ExternalMetricFeature | None:
        rows = self._eligible(metric, symbol_scope, as_of_ms)
        if not rows:
            return None
        recent = rows[-max(2, int(window)):]
        current = recent[-1]
        delta = current.value - recent[-2].value if len(recent) >= 2 else None

        velocity = None
        if len(recent) >= 2:
            dt = max(1, int(current.available_at_ms) - int(recent[-2].available_at_ms))
            velocity = (current.value - recent[-2].value) / (dt / 1000.0)

        values = [float(row.value) for row in recent]
        zscore = None
        if len(values) >= 3:
            mu = mean(values[:-1]) if len(values) > 1 else values[0]
            sd = pstdev(values[:-1]) if len(values) > 2 else 0.0
            if sd > 1e-12:
                zscore = (values[-1] - mu) / sd

        percentile = None
        if values:
            less_or_equal = sum(1 for value in values if value <= values[-1])
            percentile = less_or_equal / len(values)

        ratio = None
        ratio_name = None
        if ratio_metric:
            denominator_rows = self._eligible(ratio_metric, symbol_scope, as_of_ms)
            if denominator_rows:
                denominator = float(denominator_rows[-1].value)
                if abs(denominator) > 1e-12:
                    ratio = float(current.value) / denominator
                    ratio_name = f"{metric}/{ratio_metric}"

        body = {
            "metric": metric,
            "symbol_scope": symbol_scope,
            "as_of_ms": int(as_of_ms),
            "observation_id": current.observation_id,
            "delta": delta,
            "velocity": velocity,
            "zscore": zscore,
            "percentile": percentile,
            "ratio": ratio,
            "ratio_name": ratio_name,
        }
        return ExternalMetricFeature(
            schema="hivenance_external_metric_feature_v1",
            feature_id="extf_" + _digest(body).split(":", 1)[1][:24],
            metric=str(metric),
            symbol_scope=str(symbol_scope),
            as_of_ms=int(as_of_ms),
            observation_id=current.observation_id,
            value=float(current.value),
            delta=None if delta is None else round(float(delta), 8),
            velocity=None if velocity is None else round(float(velocity), 12),
            zscore=None if zscore is None else round(float(zscore), 8),
            percentile=None if percentile is None else round(float(percentile), 8),
            ratio=None if ratio is None else round(float(ratio), 8),
            ratio_name=ratio_name,
            evidence_root=current.source_digest,
        )

    def to_statistical_evidence(
        self,
        *,
        feature: ExternalMetricFeature,
        scope: str,
        transform: str = "SIGNED_VALUE",
        weight: float = 1.0,
    ) -> StatisticalEvidence:
        mode = str(transform).upper()
        if mode == "SIGNED_VALUE":
            realized = float(feature.value)
        elif mode == "DELTA":
            if feature.delta is None:
                raise ValueError("external_feature_delta_missing")
            realized = float(feature.delta)
        elif mode == "ZSCORE":
            if feature.zscore is None:
                raise ValueError("external_feature_zscore_missing")
            realized = float(feature.zscore)
        elif mode == "RATIO_MINUS_ONE":
            if feature.ratio is None:
                raise ValueError("external_feature_ratio_missing")
            realized = (float(feature.ratio) - 1.0) * 10000.0
        else:
            raise ValueError("external_statistical_transform_unknown")

        return StatisticalEvidence(
            evidence_id=f"stat-ext:{feature.feature_id}:{mode}",
            scope=str(scope),
            observed_at_ms=int(feature.as_of_ms) - 1,
            available_at_ms=int(feature.as_of_ms) - 1,
            realized_bps=float(realized),
            positive=bool(realized > 0.0),
            evidence_root=feature.evidence_root,
            weight=float(weight),
        )


CORE_EXTERNAL_METRICS = (
    "ETF_NET_FLOW_USD",
    "SPOT_CVD_USD",
    "SPOT_VOLUME_USD",
    "FUTURES_OPEN_INTEREST_USD",
    "FUNDING_RATE",
    "LIQUIDATION_LONG_SHORT_RATIO",
    "STABLECOIN_EXCHANGE_RESERVE_USD",
    "BTC_STABLECOIN_RESERVE_RATIO",
    "REALIZED_VOLATILITY",
    "OPTIONS_IMPLIED_VOLATILITY",
    "OPTIONS_25D_SKEW",
    "MACRO_POLICY_PROBABILITY",
    "BTC_RELATIVE_BREADTH",
)
