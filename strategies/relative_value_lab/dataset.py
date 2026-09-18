from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Any, Iterable, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .pair_lab import PairRelationshipLab


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _spread(log_a: float, log_b: float, alpha: float, beta: float) -> float:
    return log_a - (alpha + beta * log_b)


def _mean(values: Sequence[float]) -> Optional[float]:
    return statistics.fmean(values) if values else None


@dataclass(frozen=True)
class RelativeValueExample:
    schema: str
    example_id: str
    pair_id: str
    symbol_a: str
    symbol_b: str
    timestamp_ms: int
    sample_interval_sec: float
    relationship_samples: int
    hedge_alpha: float
    hedge_ratio: float
    relationship_stability: float
    half_life_seconds: Optional[float]
    structural_break_state: str
    spread: float
    spread_zscore: Optional[float]
    relative_return_1step_bps: Optional[float]
    relative_return_3step_bps: Optional[float]
    relative_return_6step_bps: Optional[float]
    pair_spread_cost_bps_proxy: Optional[float]
    quote_ofi_delta: Optional[float]
    aggressor_flow_delta: Optional[float]
    book_imbalance_delta: Optional[float]
    depth_recovery_delta: Optional[float]
    trade_intensity_sum: Optional[float]
    data_quality_min: float
    labels_bps: Mapping[str, Optional[float]] = field(default_factory=dict)
    label_timestamps_ms: Mapping[str, Optional[int]] = field(default_factory=dict)
    feature_digest: str = ""
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetBuildSummary:
    examples: int
    pairs_seen: int
    pairs_eligible_at_least_once: int
    fully_labeled_examples: int
    horizons_seconds: tuple[int, ...]
    skipped_insufficient_history: int
    skipped_ineligible_relationship: int
    skipped_missing_future: int
    authority: str = RELATIVE_VALUE_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RelativeValueDatasetBuilder:
    """Build leakage-safe relative-value examples from synchronized snapshots.

    Relationship parameters are estimated from observations at or before time t.
    Future labels use those frozen parameters and later prices. The relationship
    is never re-fit with future data while constructing a label.
    """

    def __init__(
        self,
        *,
        relationship_window_samples: int = 120,
        minimum_relationship_samples: int = 60,
        horizons_seconds: Sequence[int] = (10, 30, 60, 120),
        future_tolerance_fraction: float = 0.60,
        lab: PairRelationshipLab | None = None,
    ) -> None:
        self.relationship_window_samples = max(
            int(minimum_relationship_samples),
            int(relationship_window_samples),
        )
        self.minimum_relationship_samples = max(20, int(minimum_relationship_samples))
        self.horizons_seconds = tuple(sorted({max(1, int(value)) for value in horizons_seconds}))
        self.future_tolerance_fraction = max(0.0, min(2.0, float(future_tolerance_fraction)))
        self.lab = lab or PairRelationshipLab(min_samples=self.minimum_relationship_samples)

    @staticmethod
    def _normalize(
        rows: Iterable[Mapping[str, Any]],
    ) -> tuple[list[int], dict[int, dict[str, dict[str, Any]]]]:
        by_ts: dict[int, dict[str, dict[str, Any]]] = {}
        for row in rows:
            try:
                ts = int(row.get("timestamp_ms") or 0)
            except (TypeError, ValueError):
                continue
            symbol = str(row.get("symbol") or "")
            mid = _finite(row.get("mid"))
            if ts <= 0 or not symbol or mid is None or mid <= 0:
                continue
            normalized = dict(row)
            normalized["timestamp_ms"] = ts
            normalized["symbol"] = symbol
            normalized["mid"] = mid
            by_ts.setdefault(ts, {})[symbol] = normalized
        return sorted(by_ts), by_ts

    @staticmethod
    def _delta(a: Mapping[str, Any], b: Mapping[str, Any], key: str) -> Optional[float]:
        av = _finite(a.get(key))
        bv = _finite(b.get(key))
        if av is None or bv is None:
            return None
        return av - bv

    @staticmethod
    def _sum(a: Mapping[str, Any], b: Mapping[str, Any], key: str) -> Optional[float]:
        av = _finite(a.get(key))
        bv = _finite(b.get(key))
        if av is None or bv is None:
            return None
        return av + bv

    @staticmethod
    def _pair_cost_proxy(a: Mapping[str, Any], b: Mapping[str, Any]) -> Optional[float]:
        # Crossing two USD books would approximately pay half-spread on each leg
        # at mark-to-mid entry. This is a diagnostic proxy, not a venue route quote.
        a_spread = _finite(a.get("spread_bps"))
        b_spread = _finite(b.get("spread_bps"))
        if a_spread is None or b_spread is None:
            return None
        return 0.5 * (a_spread + b_spread)

    @staticmethod
    def _future_index(
        timestamps: Sequence[int],
        *,
        start_index: int,
        target_ms: int,
        max_lateness_ms: int,
    ) -> Optional[int]:
        lo = start_index + 1
        hi = len(timestamps)
        while lo < hi:
            mid = (lo + hi) // 2
            if timestamps[mid] < target_ms:
                lo = mid + 1
            else:
                hi = mid
        if lo >= len(timestamps):
            return None
        if timestamps[lo] - target_ms > max_lateness_ms:
            return None
        return lo

    @staticmethod
    def _step_return(
        spreads: Sequence[float],
        steps: int,
    ) -> Optional[float]:
        if len(spreads) <= steps:
            return None
        return (spreads[-1] - spreads[-1 - steps]) * 10_000.0

    def build(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        venue: str = "unknown",
        direct_routes: set[frozenset[str]] | None = None,
    ) -> tuple[list[RelativeValueExample], DatasetBuildSummary]:
        timestamps, by_ts = self._normalize(rows)
        if len(timestamps) < 2:
            return [], DatasetBuildSummary(
                examples=0,
                pairs_seen=0,
                pairs_eligible_at_least_once=0,
                fully_labeled_examples=0,
                horizons_seconds=self.horizons_seconds,
                skipped_insufficient_history=0,
                skipped_ineligible_relationship=0,
                skipped_missing_future=0,
            )

        diffs = [
            (b - a) / 1000.0
            for a, b in zip(timestamps, timestamps[1:])
            if b > a
        ]
        sample_interval_sec = float(statistics.median(diffs)) if diffs else 1.0
        max_lateness_ms = max(
            1,
            int(sample_interval_sec * 1000.0 * self.future_tolerance_fraction),
        )
        routes = direct_routes or set()

        symbols = sorted({
            symbol
            for snapshot in by_ts.values()
            for symbol in snapshot
        })
        pairs = list(combinations(symbols, 2))
        eligible_pairs: set[str] = set()
        examples: list[RelativeValueExample] = []
        skipped_history = 0
        skipped_ineligible = 0
        skipped_future = 0

        # Histories contain only observations seen up through the current loop.
        histories: dict[str, list[tuple[int, float]]] = {symbol: [] for symbol in symbols}
        spread_histories: dict[str, list[float]] = {}

        for index, ts in enumerate(timestamps):
            snapshot = by_ts[ts]
            for symbol, row in snapshot.items():
                histories[symbol].append((ts, float(row["mid"])))

            for symbol_a, symbol_b in pairs:
                row_a = snapshot.get(symbol_a)
                row_b = snapshot.get(symbol_b)
                if row_a is None or row_b is None:
                    continue

                hist_a = {stamp: price for stamp, price in histories[symbol_a][-self.relationship_window_samples:]}
                hist_b = {stamp: price for stamp, price in histories[symbol_b][-self.relationship_window_samples:]}
                common = sorted(set(hist_a).intersection(hist_b))
                if len(common) < self.minimum_relationship_samples:
                    skipped_history += 1
                    continue

                prices_a = [hist_a[stamp] for stamp in common]
                prices_b = [hist_b[stamp] for stamp in common]
                direct = frozenset((symbol_a, symbol_b)) in routes
                diagnostics, _ = self.lab.analyze(
                    symbol_a=symbol_a,
                    symbol_b=symbol_b,
                    prices_a=prices_a,
                    prices_b=prices_b,
                    sample_interval_sec=sample_interval_sec,
                    venue=venue,
                    observed_at_ms=ts,
                    direct_route_available=direct,
                )
                if (
                    diagnostics.hedge_alpha is None
                    or diagnostics.hedge_ratio is None
                    or diagnostics.spread_last is None
                ):
                    skipped_ineligible += 1
                    continue
                if not diagnostics.eligible:
                    skipped_ineligible += 1
                    continue

                eligible_pairs.add(diagnostics.pair_id)
                alpha = float(diagnostics.hedge_alpha)
                beta = float(diagnostics.hedge_ratio)
                current_spread = float(diagnostics.spread_last)

                pair_spreads = spread_histories.setdefault(diagnostics.pair_id, [])
                pair_spreads.append(current_spread)
                if len(pair_spreads) > self.relationship_window_samples:
                    del pair_spreads[0]

                labels: dict[str, Optional[float]] = {}
                label_ts: dict[str, Optional[int]] = {}
                missing_any = False
                for horizon in self.horizons_seconds:
                    target_ms = ts + horizon * 1000
                    future_index = self._future_index(
                        timestamps,
                        start_index=index,
                        target_ms=target_ms,
                        max_lateness_ms=max_lateness_ms,
                    )
                    label_key = f"{horizon}s"
                    if future_index is None:
                        labels[label_key] = None
                        label_ts[label_key] = None
                        missing_any = True
                        continue
                    future_ts = timestamps[future_index]
                    future_snapshot = by_ts[future_ts]
                    future_a = future_snapshot.get(symbol_a)
                    future_b = future_snapshot.get(symbol_b)
                    if future_a is None or future_b is None:
                        labels[label_key] = None
                        label_ts[label_key] = None
                        missing_any = True
                        continue
                    future_spread = _spread(
                        math.log(float(future_a["mid"])),
                        math.log(float(future_b["mid"])),
                        alpha,
                        beta,
                    )
                    labels[label_key] = (future_spread - current_spread) * 10_000.0
                    label_ts[label_key] = int(future_ts)

                if missing_any:
                    skipped_future += 1

                quality_a = _finite(row_a.get("data_quality"))
                quality_b = _finite(row_b.get("data_quality"))
                quality_min = min(
                    quality_a if quality_a is not None else 0.0,
                    quality_b if quality_b is not None else 0.0,
                )

                feature_payload = {
                    "pair_id": diagnostics.pair_id,
                    "timestamp_ms": ts,
                    "hedge_alpha": alpha,
                    "hedge_ratio": beta,
                    "spread": current_spread,
                    "spread_zscore": diagnostics.spread_zscore,
                    "stability": diagnostics.stability_score,
                    "half_life_seconds": diagnostics.half_life_seconds,
                    "quote_ofi_delta": self._delta(row_a, row_b, "quote_ofi_proxy"),
                    "aggressor_flow_delta": self._delta(row_a, row_b, "aggressor_flow_imbalance"),
                    "book_imbalance_delta": self._delta(row_a, row_b, "book_imbalance_25bps"),
                    "depth_recovery_delta": self._delta(row_a, row_b, "depth_recovery_score"),
                    "trade_intensity_sum": self._sum(row_a, row_b, "trade_intensity_per_sec"),
                    "pair_spread_cost_bps_proxy": self._pair_cost_proxy(row_a, row_b),
                    "data_quality_min": quality_min,
                }
                digest = _hash(feature_payload)
                examples.append(RelativeValueExample(
                    schema="hivenance_relative_value_example_v1",
                    example_id="rve_" + digest.split(":", 1)[1][:24],
                    pair_id=diagnostics.pair_id,
                    symbol_a=symbol_a,
                    symbol_b=symbol_b,
                    timestamp_ms=ts,
                    sample_interval_sec=sample_interval_sec,
                    relationship_samples=len(common),
                    hedge_alpha=alpha,
                    hedge_ratio=beta,
                    relationship_stability=diagnostics.stability_score,
                    half_life_seconds=diagnostics.half_life_seconds,
                    structural_break_state=diagnostics.structural_break_state,
                    spread=current_spread,
                    spread_zscore=diagnostics.spread_zscore,
                    relative_return_1step_bps=self._step_return(pair_spreads, 1),
                    relative_return_3step_bps=self._step_return(pair_spreads, 3),
                    relative_return_6step_bps=self._step_return(pair_spreads, 6),
                    pair_spread_cost_bps_proxy=self._pair_cost_proxy(row_a, row_b),
                    quote_ofi_delta=self._delta(row_a, row_b, "quote_ofi_proxy"),
                    aggressor_flow_delta=self._delta(row_a, row_b, "aggressor_flow_imbalance"),
                    book_imbalance_delta=self._delta(row_a, row_b, "book_imbalance_25bps"),
                    depth_recovery_delta=self._delta(row_a, row_b, "depth_recovery_score"),
                    trade_intensity_sum=self._sum(row_a, row_b, "trade_intensity_per_sec"),
                    data_quality_min=quality_min,
                    labels_bps=labels,
                    label_timestamps_ms=label_ts,
                    feature_digest=digest,
                    authority=RELATIVE_VALUE_AUTHORITY,
                    execution_eligible=False,
                ))

        fully_labeled = sum(
            1 for example in examples
            if all(example.labels_bps.get(f"{h}s") is not None for h in self.horizons_seconds)
        )
        summary = DatasetBuildSummary(
            examples=len(examples),
            pairs_seen=len(pairs),
            pairs_eligible_at_least_once=len(eligible_pairs),
            fully_labeled_examples=fully_labeled,
            horizons_seconds=self.horizons_seconds,
            skipped_insufficient_history=skipped_history,
            skipped_ineligible_relationship=skipped_ineligible,
            skipped_missing_future=skipped_future,
        )
        return examples, summary
