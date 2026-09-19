from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _clamp(v: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(v)))


@dataclass(frozen=True)
class TemporalTextureReceipt:
    schema: str
    sample_size: int
    median_interval_ms: Optional[float]
    mean_interval_ms: Optional[float]
    jitter_ms: float
    jitter_norm: float
    drift_norm: float
    burstiness: float
    entropy_signature: float
    dominant_frequency_hz: float
    sequence_class: str
    persistence: float
    cadence_coherence: float
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self):
        return asdict(self)


class TemporalTexture:
    """AATL/Harmonic-style temporal texture for Phoenix musical cognition."""

    def __init__(
        self,
        *,
        baseline_median_ms: float = 5_000.0,
        baseline_jitter_ms: float = 2_500.0,
        short_threshold_ms: float = 2_000.0,
        expected_burstiness: float = 0.10,
        entropy_target: float = 0.70,
        entropy_tolerance: float = 0.30,
    ) -> None:
        self.baseline_median_ms = max(1.0, float(baseline_median_ms))
        self.baseline_jitter_ms = max(1.0, float(baseline_jitter_ms))
        self.short_threshold_ms = max(1.0, float(short_threshold_ms))
        self.expected_burstiness = _clamp(expected_burstiness)
        self.entropy_target = _clamp(entropy_target)
        self.entropy_tolerance = max(0.01, float(entropy_tolerance))

    def _entropy(self, intervals: Sequence[float]) -> float:
        if not intervals:
            return 0.0
        buckets = [
            0.20 * self.baseline_median_ms,
            0.50 * self.baseline_median_ms,
            1.00 * self.baseline_median_ms,
            2.00 * self.baseline_median_ms,
        ]
        counts = [0] * (len(buckets) + 1)
        for value in intervals:
            placed = False
            for i, limit in enumerate(buckets):
                if value <= limit:
                    counts[i] += 1
                    placed = True
                    break
            if not placed:
                counts[-1] += 1
        total = float(sum(counts))
        entropy = 0.0
        for count in counts:
            if count:
                p = count / total
                entropy -= p * math.log(p, 2)
        max_entropy = math.log(len(counts), 2)
        return _clamp(entropy / max_entropy if max_entropy else 0.0)

    def score(self, timestamps_ms: Sequence[int]) -> TemporalTextureReceipt:
        ordered = sorted(int(x) for x in timestamps_ms)
        intervals = [max(0.0, float(b - a)) for a, b in zip(ordered, ordered[1:])]
        if not intervals:
            return TemporalTextureReceipt(
                schema="hivenance_temporal_texture_v1",
                sample_size=0,
                median_interval_ms=None,
                mean_interval_ms=None,
                jitter_ms=0.0,
                jitter_norm=0.0,
                drift_norm=0.0,
                burstiness=0.0,
                entropy_signature=0.0,
                dominant_frequency_hz=0.0,
                sequence_class="cold_start",
                persistence=0.0,
                cadence_coherence=0.0,
            )

        median = float(statistics.median(intervals))
        mean = float(statistics.fmean(intervals))
        jitter = float(statistics.pstdev(intervals)) if len(intervals) > 1 else 0.0
        jitter_norm = _clamp(jitter / self.baseline_jitter_ms)
        drift_norm = _clamp(abs(median - self.baseline_median_ms) / self.baseline_median_ms)
        short_ratio = sum(1 for x in intervals if x <= self.short_threshold_ms) / len(intervals)
        burstiness = _clamp(max(0.0, short_ratio - self.expected_burstiness))
        entropy = self._entropy(intervals)
        dominant_frequency = 1000.0 / max(median, 1.0)

        cv = jitter / max(mean, 1.0)
        if median <= self.short_threshold_ms and cv < 0.35:
            sequence_class = "rapid_regular"
        elif cv < 0.25:
            sequence_class = "regular"
        elif cv > 0.90:
            sequence_class = "chaotic"
        else:
            sequence_class = "adaptive"

        persistence = _clamp(1.0 - 0.55 * jitter_norm - 0.45 * drift_norm)
        entropy_fit = 1.0 - _clamp(abs(entropy - self.entropy_target) / self.entropy_tolerance)
        cadence_coherence = _clamp(
            0.35 * (1.0 - jitter_norm)
            + 0.30 * (1.0 - drift_norm)
            + 0.20 * (1.0 - burstiness)
            + 0.15 * entropy_fit
        )

        return TemporalTextureReceipt(
            schema="hivenance_temporal_texture_v1",
            sample_size=len(intervals),
            median_interval_ms=round(median, 6),
            mean_interval_ms=round(mean, 6),
            jitter_ms=round(jitter, 6),
            jitter_norm=round(jitter_norm, 6),
            drift_norm=round(drift_norm, 6),
            burstiness=round(burstiness, 6),
            entropy_signature=round(entropy, 6),
            dominant_frequency_hz=round(dominant_frequency, 6),
            sequence_class=sequence_class,
            persistence=round(persistence, 6),
            cadence_coherence=round(cadence_coherence, 6),
        )