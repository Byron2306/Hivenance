from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

AUTHORITY="PUBLIC_MARKET_RESEARCH_CONTEXT_ONLY_NO_EXECUTION_AUTHORITY"


def _sign(value: float, deadband: float = 0.0) -> int:
    if value > deadband:
        return 1
    if value < -deadband:
        return -1
    return 0


def _bias(sign: int) -> str:
    return "UP" if sign > 0 else "DOWN" if sign < 0 else "NEUTRAL"


def _median(values: Iterable[float]) -> float:
    vals=[float(v) for v in values]
    return statistics.median(vals) if vals else 0.0


@dataclass(frozen=True)
class HorizonContext:
    symbol: str
    timestamp: float
    micro: dict[str,Any]
    meso: dict[str,Any]
    macro: dict[str,Any]
    alignment: str
    regime_hint: str
    relative_strength: dict[str,Any]
    readiness: dict[str,bool]
    authority: str=AUTHORITY

    def to_dict(self) -> dict[str,Any]:
        return {
            "symbol":self.symbol,
            "timestamp":self.timestamp,
            "micro":self.micro,
            "meso":self.meso,
            "macro":self.macro,
            "alignment":self.alignment,
            "regime_hint":self.regime_hint,
            "relative_strength":self.relative_strength,
            "readiness":self.readiness,
            "authority":self.authority,
        }


class HorizonContextAgent:
    """Research-only micro/meso/macro context synthesizer.

    This agent never emits an order instruction. It describes observed direction,
    relative strength, volatility and cross-horizon alignment so another research
    process can later test whether this context improves decisions.
    """

    def __init__(self, *, deadband_bps: float = 1.0) -> None:
        self.deadband_bps=max(0.0,float(deadband_bps))

    def build(
        self,
        *,
        symbol: str,
        timestamp: float,
        returns_bps: dict[str,float | None],
        realized_vol_bps: dict[str,float | None],
        ticker_24h: dict[str,float | None],
        cross_sectional_returns: dict[str,list[float]],
    ) -> HorizonContext:
        r10=float(returns_bps.get("10s") or 0.0)
        r30=float(returns_bps.get("30s") or 0.0)
        r2m=float(returns_bps.get("2m") or 0.0)
        r5m=float(returns_bps.get("5m") or 0.0)
        r15m=returns_bps.get("15m")
        r1h=returns_bps.get("1h")

        micro_ready=returns_bps.get("30s") is not None
        meso_ready=returns_bps.get("2m") is not None
        macro_15m_ready=r15m is not None
        macro_1h_ready=r1h is not None

        micro_score=0.60*r10+0.40*r30
        meso_parts=[]
        if returns_bps.get("2m") is not None:
            meso_parts.append(0.45*r2m)
        if returns_bps.get("5m") is not None:
            meso_parts.append(0.55*r5m)
        meso_score=sum(meso_parts) if meso_parts else 0.0

        open_24h=float(ticker_24h.get("open") or 0.0)
        last=float(ticker_24h.get("last") or 0.0)
        high=float(ticker_24h.get("high") or 0.0)
        low=float(ticker_24h.get("low") or 0.0)
        ret24=(last/open_24h-1.0)*10000.0 if open_24h>0 and last>0 else 0.0
        range_pos=(last-low)/max(high-low,1e-12) if high>low and last>0 else 0.5

        macro_signs=[]
        if macro_15m_ready:
            macro_signs.append(_sign(float(r15m),self.deadband_bps))
        if macro_1h_ready:
            macro_signs.append(_sign(float(r1h),self.deadband_bps))
        macro_signs.append(_sign(ret24,self.deadband_bps*4.0))
        macro_vote=sum(macro_signs)
        macro_direction=_sign(float(macro_vote),0.0)
        macro_conviction=abs(macro_vote)/max(1,len(macro_signs))

        micro_direction=_sign(micro_score,self.deadband_bps)
        meso_direction=_sign(meso_score,self.deadband_bps)

        directional=[d for d in (micro_direction,meso_direction,macro_direction) if d!=0]
        if directional and all(d>0 for d in directional):
            alignment="ALIGNED_UP"
        elif directional and all(d<0 for d in directional):
            alignment="ALIGNED_DOWN"
        elif not directional:
            alignment="NEUTRAL"
        else:
            alignment="CONFLICT"

        vol5=float(realized_vol_bps.get("5m") or 0.0)
        if alignment=="ALIGNED_UP" and macro_conviction>=0.5:
            regime_hint="TREND_UP"
        elif alignment=="ALIGNED_DOWN" and macro_conviction>=0.5:
            regime_hint="TREND_DOWN"
        elif vol5>=15.0 and abs(meso_score)>=5.0:
            regime_hint="VOL_EXPANSION"
        elif abs(meso_score)<=self.deadband_bps*2.0:
            regime_hint="CHOP_RANGE"
        else:
            regime_hint="MIXED"

        rel={}
        for horizon in ("30s","2m","5m","15m","1h"):
            own=returns_bps.get(horizon)
            peers=cross_sectional_returns.get(horizon) or []
            rel[horizon]=None if own is None or not peers else float(own)-_median(peers)

        return HorizonContext(
            symbol=symbol,
            timestamp=float(timestamp),
            micro={
                "return_10s_bps":returns_bps.get("10s"),
                "return_30s_bps":returns_bps.get("30s"),
                "score_bps":round(micro_score,6),
                "bias":_bias(micro_direction),
                "realized_vol_30s_bps":realized_vol_bps.get("30s"),
            },
            meso={
                "return_2m_bps":returns_bps.get("2m"),
                "return_5m_bps":returns_bps.get("5m"),
                "score_bps":round(meso_score,6),
                "bias":_bias(meso_direction),
                "realized_vol_5m_bps":realized_vol_bps.get("5m"),
            },
            macro={
                "return_15m_bps":r15m,
                "return_1h_bps":r1h,
                "return_24h_bps":round(ret24,6),
                "range_position_24h":round(range_pos,6),
                "bias":_bias(macro_direction),
                "conviction":round(macro_conviction,6),
                "observed_15m_ready":macro_15m_ready,
                "observed_1h_ready":macro_1h_ready,
            },
            alignment=alignment,
            regime_hint=regime_hint,
            relative_strength=rel,
            readiness={
                "micro":micro_ready,
                "meso":meso_ready,
                "macro_15m":macro_15m_ready,
                "macro_1h":macro_1h_ready,
                "macro_24h_ticker":open_24h>0 and last>0,
            },
        )
