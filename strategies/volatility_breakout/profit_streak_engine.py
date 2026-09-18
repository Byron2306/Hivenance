from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from typing import Any, Deque, Mapping, Optional


@dataclass(frozen=True)
class EquityPoint:
    ts: float
    equity_usd: float
    cumulative_cost_usd: float = 0.0
    context: Optional[Mapping[str, Any]] = None


@dataclass
class ProfitStreak:
    streak_id: str
    started_ts: float
    start_equity_usd: float
    peak_equity_usd: float
    peak_ts: float
    cumulative_cost_start_usd: float
    observations: int = 1
    retracements: int = 0
    max_retracement_usd: float = 0.0
    ended_ts: Optional[float] = None
    end_equity_usd: Optional[float] = None
    cumulative_cost_end_usd: Optional[float] = None
    context_start: Optional[Mapping[str, Any]] = None
    context_peak: Optional[Mapping[str, Any]] = None
    context_end: Optional[Mapping[str, Any]] = None

    def receipt(self) -> dict[str, Any]:
        end_ts = self.ended_ts if self.ended_ts is not None else self.peak_ts
        end_equity = self.end_equity_usd if self.end_equity_usd is not None else self.peak_equity_usd
        cost_end = self.cumulative_cost_end_usd if self.cumulative_cost_end_usd is not None else self.cumulative_cost_start_usd
        duration = max(0.0, end_ts - self.started_ts)
        gross = max(0.0, self.peak_equity_usd - self.start_equity_usd)
        net = end_equity - self.start_equity_usd
        cost = max(0.0, cost_end - self.cumulative_cost_start_usd)
        return {
            "schema": "hivenance_profit_streak_receipt_v1",
            "streak_id": self.streak_id,
            "started_ts": self.started_ts,
            "ended_ts": end_ts,
            "duration_sec": duration,
            "start_equity_usd": self.start_equity_usd,
            "end_equity_usd": end_equity,
            "peak_equity_usd": self.peak_equity_usd,
            "gross_advance_usd": gross,
            "net_advance_usd": net,
            "max_retracement_usd": self.max_retracement_usd,
            "retracements": self.retracements,
            "observations": self.observations,
            "cost_usd": cost,
            "profit_velocity_usd_per_sec": net / duration if duration else 0.0,
            "cost_to_gross_ratio": cost / gross if gross else 0.0,
            "context_start": dict(self.context_start or {}),
            "context_peak": dict(self.context_peak or {}),
            "context_end": dict(self.context_end or {}),
            "authority": "paper_observation_only_no_order_authority",
        }


class ProfitStreakEngine:
    """Research-only portfolio-equity streak observer.

    This deliberately sits beside trade-level WIN/LOSS evidence. It never
    submits orders, promotes models, changes capital stages, or weakens the
    Phase-6/Phase-7 authority boundary.
    """

    authority = "paper_observation_only_no_order_authority"

    def __init__(
        self,
        *,
        fast_horizon_sec: float = 5.0,
        slow_horizon_sec: float = 10.0,
        min_advance_usd: float = 0.0,
        max_retracement_usd: float = 0.05,
    ) -> None:
        self.fast_horizon_sec = max(0.1, float(fast_horizon_sec))
        self.slow_horizon_sec = max(self.fast_horizon_sec, float(slow_horizon_sec))
        self.min_advance_usd = max(0.0, float(min_advance_usd))
        self.max_retracement_usd = max(0.0, float(max_retracement_usd))
        self._history: Deque[EquityPoint] = deque()
        self._active: Optional[ProfitStreak] = None
        self._completed: list[ProfitStreak] = []
        self._sequence = 0

    def _at_or_before(self, ts: float) -> Optional[EquityPoint]:
        candidate = None
        for point in self._history:
            if point.ts <= ts:
                candidate = point
            else:
                break
        return candidate

    def observe(self, point: EquityPoint) -> list[dict[str, Any]]:
        if self._history and point.ts <= self._history[-1].ts:
            raise ValueError("equity observations must be strictly time ordered")
        self._history.append(point)
        cutoff = point.ts - self.slow_horizon_sec * 3.0
        while len(self._history) > 2 and self._history[1].ts < cutoff:
            self._history.popleft()

        fast = self._at_or_before(point.ts - self.fast_horizon_sec)
        slow = self._at_or_before(point.ts - self.slow_horizon_sec)
        if fast is None or slow is None:
            return []

        d_fast = point.equity_usd - fast.equity_usd
        d_slow = point.equity_usd - slow.equity_usd
        advancing = d_fast > self.min_advance_usd and d_slow > self.min_advance_usd
        context = dict(point.context or {})
        events: list[dict[str, Any]] = []

        if self._active is None:
            if advancing:
                self._sequence += 1
                self._active = ProfitStreak(
                    streak_id=f"profit-streak-{self._sequence:08d}",
                    started_ts=point.ts,
                    start_equity_usd=point.equity_usd,
                    peak_equity_usd=point.equity_usd,
                    peak_ts=point.ts,
                    cumulative_cost_start_usd=point.cumulative_cost_usd,
                    context_start=context,
                    context_peak=context,
                )
                events.append(self._event("STREAK_START", point, d_fast, d_slow))
            return events

        active = self._active
        active.observations += 1
        if point.equity_usd > active.peak_equity_usd:
            active.peak_equity_usd = point.equity_usd
            active.peak_ts = point.ts
            active.context_peak = context
            events.append(self._event("STREAK_PEAK", point, d_fast, d_slow))
        else:
            retracement = max(0.0, active.peak_equity_usd - point.equity_usd)
            if retracement:
                active.retracements += 1
                active.max_retracement_usd = max(active.max_retracement_usd, retracement)
                events.append(self._event("STREAK_RETRACE", point, d_fast, d_slow))

        retracement = max(0.0, active.peak_equity_usd - point.equity_usd)
        terminate = retracement > self.max_retracement_usd or (d_fast <= 0.0 and d_slow <= 0.0)
        if terminate:
            active.ended_ts = point.ts
            active.end_equity_usd = point.equity_usd
            active.cumulative_cost_end_usd = point.cumulative_cost_usd
            active.context_end = context
            events.append(self._event("STREAK_END", point, d_fast, d_slow))
            self._completed.append(active)
            self._active = None
        elif advancing:
            events.append(self._event("STREAK_CONTINUE", point, d_fast, d_slow))
        return events

    def _event(self, kind: str, point: EquityPoint, d_fast: float, d_slow: float) -> dict[str, Any]:
        return {
            "kind": kind,
            "ts": point.ts,
            "equity_usd": point.equity_usd,
            "delta_fast_usd": d_fast,
            "delta_slow_usd": d_slow,
            "streak_id": self._active.streak_id if self._active else None,
            "context": dict(point.context or {}),
            "authority": self.authority,
        }

    def finalize(self) -> Optional[dict[str, Any]]:
        if self._active is None:
            return None
        point = self._history[-1]
        self._active.ended_ts = point.ts
        self._active.end_equity_usd = point.equity_usd
        self._active.cumulative_cost_end_usd = point.cumulative_cost_usd
        self._active.context_end = dict(point.context or {})
        receipt = self._active.receipt()
        self._completed.append(self._active)
        self._active = None
        return receipt

    def completed_receipts(self) -> list[dict[str, Any]]:
        return [streak.receipt() for streak in self._completed]

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "hivenance_profit_streak_snapshot_v1",
            "authority": self.authority,
            "fast_horizon_sec": self.fast_horizon_sec,
            "slow_horizon_sec": self.slow_horizon_sec,
            "min_advance_usd": self.min_advance_usd,
            "max_retracement_usd": self.max_retracement_usd,
            "active": self._active.receipt() if self._active else None,
            "completed": self.completed_receipts(),
        }
