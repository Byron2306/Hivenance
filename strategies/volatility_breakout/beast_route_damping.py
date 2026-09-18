from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

try:
    import fcntl
except Exception:  # pragma: no cover - non-Unix fallback
    fcntl = None


@dataclass
class RoutePenalty:
    route_id: str
    penalty: float = 0.0
    updated_at: float = 0.0
    events: int = 0
    last_event: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HivenanceRouteDampener:
    """BEAST-inspired route-flap damping for research-only worker/slice paths."""

    EVENT_WEIGHTS = {
        "success": -35.0,
        "profitable_after_costs": -50.0,
        "admission_refused": 250.0,
        "world_state_stale": 300.0,
        "hostile_spread": 250.0,
        "low_data_quality": 350.0,
        "insufficient_depth": 250.0,
        "hostile_liquidity_class": 300.0,
        "wrong_regime": 450.0,
        "false_breakout": 425.0,
        "spread_too_wide": 325.0,
        "late_entry": 250.0,
        "late_entry_or_missed_fill": 300.0,
        "partial_fill_drag": 200.0,
        "cost_drag": 275.0,
        "no_follow_through": 225.0,
        "stale_or_low_quality_data": 350.0,
        "venue_rejection": 275.0,
        "unknown_order_state": 650.0,
    }

    def __init__(
        self,
        *,
        path: str | Path,
        suppress_at: float = 1000.0,
        half_life_seconds: float = 900.0,
    ) -> None:
        self.path = Path(path)
        self.suppress_at = max(1.0, float(suppress_at or 1000.0))
        self.half_life_seconds = max(1.0, float(half_life_seconds or 900.0))
        self._lock = RLock()
        self.routes: dict[str, RoutePenalty] = {}
        self._load()

    @staticmethod
    def route_id_from_candidate(candidate: Mapping[str, Any], *, policy: str = "", scenario: str = "") -> str:
        return "|".join(
            str(part or "unknown")
            for part in (
                candidate.get("model_id"),
                candidate.get("hypothesis"),
                candidate.get("regime_hint"),
                candidate.get("cohort_bucket"),
                candidate.get("symbol_class"),
                candidate.get("symbol"),
                candidate.get("horizon_seconds"),
                candidate.get("direction"),
                policy or "*",
                scenario or "*",
            )
        )

    def record(self, route_id: str, event: str, *, now: float | None = None) -> RoutePenalty:
        if not route_id:
            raise ValueError("route_id required")
        now = time.time() if now is None else float(now)
        weight = self.EVENT_WEIGHTS.get(str(event), 0.0)
        with self._lock:
            with self._state_lock():
                self._load()
                score = self.routes.setdefault(route_id, RoutePenalty(route_id=route_id, updated_at=now))
                score.penalty = self._decayed(score, now) + weight
                score.penalty = max(0.0, score.penalty)
                score.updated_at = now
                score.events += 1
                score.last_event = str(event)
                self._persist()
                return RoutePenalty(**score.to_dict())

    def record_many(self, events: Mapping[tuple[str, str], int], *, now: float | None = None) -> dict[str, int]:
        """Apply compacted route events in one locked persistence pass."""
        now = time.time() if now is None else float(now)
        applied = 0
        ignored = 0
        with self._lock:
            with self._state_lock():
                self._load()
                for (route_id, event), count in events.items():
                    if not route_id or count <= 0:
                        ignored += 1
                        continue
                    weight = self.EVENT_WEIGHTS.get(str(event), 0.0)
                    score = self.routes.setdefault(route_id, RoutePenalty(route_id=route_id, updated_at=now))
                    score.penalty = self._decayed(score, now) + (weight * int(count))
                    score.penalty = max(0.0, score.penalty)
                    score.updated_at = now
                    score.events += int(count)
                    score.last_event = str(event)
                    applied += int(count)
                self._persist()
        return {"applied": applied, "ignored": ignored}

    def score(self, route_id: str, *, now: float | None = None) -> RoutePenalty:
        now = time.time() if now is None else float(now)
        with self._lock:
            with self._state_lock():
                self._load()
                score = self.routes.get(route_id)
                if score is None:
                    return RoutePenalty(route_id=route_id, updated_at=now)
                score.penalty = self._decayed(score, now)
                score.updated_at = now
                self._persist()
                return RoutePenalty(**score.to_dict())

    def suppressed(self, route_id: str, *, now: float | None = None) -> bool:
        return self.score(route_id, now=now).penalty >= self.suppress_at

    def snapshot(self, *, limit: int = 50, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else float(now)
        with self._lock:
            with self._state_lock():
                self._load()
                rows = []
                for route_id, score in self.routes.items():
                    score.penalty = self._decayed(score, now)
                    score.updated_at = now
                    rows.append({
                        **score.to_dict(),
                        "suppressed": score.penalty >= self.suppress_at,
                    })
                self._persist()
        rows = sorted(rows, key=lambda item: float(item.get("penalty") or 0.0), reverse=True)
        return {
            "schema": "hivenance_beast_route_damping_snapshot_v1",
            "authority": "research_selection_only",
            "source_inspiration": "edgek_beast_route_flap_dampener",
            "suppress_at": self.suppress_at,
            "half_life_seconds": self.half_life_seconds,
            "routes": rows[: max(1, int(limit))],
            "suppressed_count": sum(1 for row in rows if bool(row.get("suppressed"))),
        }

    def _decayed(self, score: RoutePenalty, now: float) -> float:
        elapsed = max(0.0, now - float(score.updated_at or now))
        return float(score.penalty or 0.0) * math.pow(0.5, elapsed / self.half_life_seconds)

    def _load(self) -> None:
        if not self.path.exists():
            self.routes = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            rows = raw.get("routes", raw) if isinstance(raw, dict) else {}
            self.routes = {
                str(route_id): RoutePenalty(**payload)
                for route_id, payload in rows.items()
                if isinstance(payload, dict)
            }
        except Exception:
            self.routes = {}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "hivenance_beast_route_damping_state_v1",
            "authority": "research_selection_only",
            "routes": {route_id: score.to_dict() for route_id, score in sorted(self.routes.items())},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    @contextmanager
    def _state_lock(self):
        if fcntl is None:
            yield
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
