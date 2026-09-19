from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ParticipationObservation:
    observed_at_ms: int
    volume: float
    realized_move_bps: float | None = None


@dataclass(frozen=True)
class TemporalParticipationEvidence:
    schema: str
    evidence_id: str
    observed_at_ms: int
    utc_hour: int
    weekday: int
    weekend: bool
    utc_block_4h: str
    session_proxies: tuple[str, ...]
    historical_same_hour_n: int
    volume_ratio_to_same_hour_median: float | None
    move_ratio_to_same_hour_median: float | None
    activity_state: str
    evidence_root: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemporalParticipationBee:
    """UTC participation topology from information available strictly before T.

    Session labels are clock proxies only. They do not infer trader nationality.
    """

    version = "hivenance.temporal_participation_bee.v1"

    def __init__(self, *, min_same_hour_samples: int = 5) -> None:
        self.min_same_hour_samples = max(1, int(min_same_hour_samples))

    def observe(
        self,
        *,
        observed_at_ms: int,
        volume: float,
        history: Sequence[ParticipationObservation],
        realized_move_bps: float | None = None,
    ) -> TemporalParticipationEvidence:
        now = datetime.fromtimestamp(observed_at_ms / 1000.0, tz=timezone.utc)
        prior = [x for x in history if int(x.observed_at_ms) < int(observed_at_ms)]
        same_hour = [
            x for x in prior
            if datetime.fromtimestamp(x.observed_at_ms / 1000.0, tz=timezone.utc).hour == now.hour
        ]
        volume_ratio = None
        move_ratio = None
        if len(same_hour) >= self.min_same_hour_samples:
            med_volume = statistics.median(max(0.0, float(x.volume)) for x in same_hour)
            if med_volume > 0:
                volume_ratio = max(0.0, float(volume)) / med_volume
            moves = [
                abs(float(x.realized_move_bps))
                for x in same_hour if x.realized_move_bps is not None
            ]
            if realized_move_bps is not None and len(moves) >= self.min_same_hour_samples:
                med_move = statistics.median(moves)
                if med_move > 0:
                    move_ratio = abs(float(realized_move_bps)) / med_move

        if volume_ratio is None:
            state = "PARTICIPATION_UNKNOWN"
        elif volume_ratio >= 1.5:
            state = "PARTICIPATION_ELEVATED"
        elif volume_ratio <= 0.67:
            state = "PARTICIPATION_THIN"
        else:
            state = "PARTICIPATION_NORMAL"

        sessions = self._session_proxies(now.hour)
        payload = {
            "observed_at_ms": int(observed_at_ms),
            "utc_hour": now.hour,
            "weekday": now.weekday(),
            "weekend": now.weekday() >= 5,
            "volume": float(volume),
            "realized_move_bps": realized_move_bps,
            "same_hour_n": len(same_hour),
            "volume_ratio": volume_ratio,
            "move_ratio": move_ratio,
            "sessions": sessions,
        }
        return TemporalParticipationEvidence(
            schema="hivenance_temporal_participation_evidence_v1",
            evidence_id="tpe_" + _digest(payload).split(":", 1)[1][:24],
            observed_at_ms=int(observed_at_ms),
            utc_hour=now.hour,
            weekday=now.weekday(),
            weekend=now.weekday() >= 5,
            utc_block_4h=f"{(now.hour // 4) * 4:02d}-{((now.hour // 4) * 4 + 4) % 24:02d}UTC",
            session_proxies=sessions,
            historical_same_hour_n=len(same_hour),
            volume_ratio_to_same_hour_median=volume_ratio,
            move_ratio_to_same_hour_median=move_ratio,
            activity_state=state,
            evidence_root=_digest(payload),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def _session_proxies(hour: int) -> tuple[str, ...]:
        labels = []
        # Broad UTC clock proxies only, intentionally overlapping.
        if 0 <= hour < 8:
            labels.append("ASIA_CLOCK_PROXY")
        if 7 <= hour < 16:
            labels.append("EUROPE_CLOCK_PROXY")
        if 13 <= hour < 22:
            labels.append("AMERICAS_CLOCK_PROXY")
        if not labels:
            labels.append("GLOBAL_TRANSITION_PROXY")
        return tuple(labels)
