from __future__ import annotations

from dataclasses import asdict, dataclass
from math import log
from statistics import fmean, pstdev
from typing import Any, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


@dataclass(frozen=True)
class EdgeVoice:
    family: str
    state: str
    score: float
    confidence: float
    features: dict[str, float]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EdgeEcologySnapshot:
    timestamp_ms: int
    pair_id: str
    voices: tuple[EdgeVoice, ...]
    hypothesis: str = (
        "Extreme relative-value displacement is more likely to mean-revert when "
        "one-sided aggressive flow decelerates or is absorbed than when directional "
        "flow remains persistent."
    )
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def voice(self, family: str) -> EdgeVoice | None:
        return next((v for v in self.voices if v.family == family), None)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["voices"] = [v.to_dict() for v in self.voices]
        return d


class EdgeEcology:
    """Independent economic voices. Describes state; never authorizes a trade."""

    version = "hivenance.edge_ecology.v1"

    @staticmethod
    def flow_voice(*, taker_buy_volume: float, taker_sell_volume: float,
                   previous_imbalance: float | None = None) -> EdgeVoice:
        total = max(1e-12, taker_buy_volume + taker_sell_volume)
        imbalance = _clip((taker_buy_volume - taker_sell_volume) / total)
        prior = imbalance if previous_imbalance is None else _clip(previous_imbalance)
        deceleration = abs(prior) - abs(imbalance)
        if abs(imbalance) < 0.10 and abs(prior) >= 0.25:
            state = "AGGRESSIVE_FLOW_EXHAUSTING"
        elif abs(imbalance) >= 0.35 and deceleration <= 0:
            state = "DIRECTIONAL_FLOW_PERSISTENT"
        else:
            state = "FLOW_MIXED"
        return EdgeVoice("FLOW", state, imbalance, min(1.0, abs(imbalance) * 1.8),
                         {"imbalance": imbalance, "deceleration": deceleration})

    @staticmethod
    def liquidity_voice(*, bid_depth: float, ask_depth: float, spread_bps: float,
                        previous_bid_depth: float | None = None,
                        previous_ask_depth: float | None = None) -> EdgeVoice:
        total = max(1e-12, bid_depth + ask_depth)
        imbalance = _clip((bid_depth - ask_depth) / total)
        recovery = 0.0
        if previous_bid_depth is not None and previous_ask_depth is not None:
            old_total = max(1e-12, previous_bid_depth + previous_ask_depth)
            recovery = (total - old_total) / old_total
        if recovery > 0.10 and spread_bps <= 10:
            state = "LIQUIDITY_RECOVERING"
        elif spread_bps > 20 or recovery < -0.20:
            state = "LIQUIDITY_FRAGILE"
        else:
            state = "LIQUIDITY_STABLE"
        confidence = min(1.0, abs(imbalance) + min(abs(recovery), 1.0) + min(spread_bps / 50.0, 1.0))
        return EdgeVoice("LIQUIDITY", state, imbalance, confidence,
                         {"depth_imbalance": imbalance, "depth_recovery": recovery, "spread_bps": spread_bps})

    @staticmethod
    def carry_voice(*, funding_rate: float, basis_bps: float,
                    previous_funding_rate: float | None = None) -> EdgeVoice:
        acceleration = 0.0 if previous_funding_rate is None else funding_rate - previous_funding_rate
        pressure = _clip(funding_rate * 1000.0 + basis_bps / 100.0)
        if abs(pressure) >= 0.50 and pressure * acceleration >= 0:
            state = "LEVERAGE_PRESSURE_BUILDING"
        elif abs(pressure) >= 0.25 and pressure * acceleration < 0:
            state = "LEVERAGE_PRESSURE_EASING"
        else:
            state = "CARRY_NEUTRAL"
        return EdgeVoice("CARRY", state, pressure, min(1.0, abs(pressure)),
                         {"funding_rate": funding_rate, "basis_bps": basis_bps, "funding_acceleration": acceleration})

    @staticmethod
    def trend_voice(*, returns: Sequence[float]) -> EdgeVoice:
        xs = [float(x) for x in returns]
        if not xs:
            return EdgeVoice("TREND", "TREND_UNKNOWN", 0.0, 0.0, {})
        fast = sum(xs[-min(3, len(xs)):])
        slow = sum(xs)
        agreement = 1.0 if fast * slow > 0 else 0.0
        score = _clip((fast + slow) * 25.0)
        state = "TREND_PERSISTENT" if agreement and abs(score) >= 0.15 else "TREND_WEAK_OR_CONFLICTED"
        return EdgeVoice("TREND", state, score, min(1.0, abs(score)),
                         {"fast_return": fast, "slow_return": slow, "horizon_agreement": agreement})

    @staticmethod
    def volatility_voice(*, returns: Sequence[float], baseline_vol: float | None = None) -> EdgeVoice:
        xs = [float(x) for x in returns]
        vol = pstdev(xs) if len(xs) >= 2 else 0.0
        base = vol if baseline_vol is None else max(1e-12, baseline_vol)
        ratio = vol / max(1e-12, base)
        if ratio >= 1.5:
            state = "VOL_EXPANSION"
        elif ratio <= 0.67:
            state = "VOL_COMPRESSION"
        else:
            state = "VOL_NORMAL"
        return EdgeVoice("VOLATILITY", state, _clip(log(max(ratio, 1e-12)) / 2.0),
                         min(1.0, abs(ratio - 1.0)), {"realized_vol": vol, "vol_ratio": ratio})

    def snapshot(self, *, timestamp_ms: int, pair_id: str, voices: Sequence[EdgeVoice]) -> EdgeEcologySnapshot:
        families = [v.family for v in voices]
        if len(families) != len(set(families)):
            raise ValueError("edge_ecology_duplicate_family")
        return EdgeEcologySnapshot(timestamp_ms=int(timestamp_ms), pair_id=str(pair_id), voices=tuple(voices))
