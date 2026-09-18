from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _finite(value: Any) -> Optional[float]:
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class MicrostructureSnapshot:
    schema: str
    symbol: str
    timestamp_ms: int
    best_bid: Optional[float]
    best_ask: Optional[float]
    mid: Optional[float]
    spread_bps: Optional[float]
    bid_depth_usd_5bps: Optional[float]
    ask_depth_usd_5bps: Optional[float]
    bid_depth_usd_10bps: Optional[float]
    ask_depth_usd_10bps: Optional[float]
    bid_depth_usd_25bps: Optional[float]
    ask_depth_usd_25bps: Optional[float]
    book_imbalance_25bps: Optional[float]
    quote_ofi_proxy: Optional[float]
    aggressor_buy_usd: Optional[float]
    aggressor_sell_usd: Optional[float]
    aggressor_flow_imbalance: Optional[float]
    trade_count: int
    trade_intensity_per_sec: Optional[float]
    depth_recovery_score: Optional[float]
    data_quality: float
    source_notes: tuple[str, ...] = field(default_factory=tuple)
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str,Any]:
        return asdict(self)


class SequentialMicrostructureEngine:
    """Compute public-market microstructure evidence from sequential books/trades.

    The quote OFI field is explicitly a proxy based on best-price/size changes.
    It must not be represented as full message-level exchange order flow.
    """

    def __init__(self, *, history: int = 240) -> None:
        self._last_top: dict[str,tuple[float,float,float,float]]={}
        self._last_depth: dict[str,float]={}
        self._trade_counts: dict[str,deque[int]]={}
        self.history=max(20,int(history))

    @staticmethod
    def _levels(orderbook: dict[str,Any], side: str) -> list[tuple[float,float]]:
        output=[]
        for row in orderbook.get(side) or []:
            if not isinstance(row,(list,tuple)) or len(row)<2:
                continue
            price=_finite(row[0])
            amount=_finite(row[1])
            if price is None or amount is None or price<=0 or amount<0:
                continue
            output.append((price,amount))
        return output

    @staticmethod
    def _depth(levels: Sequence[tuple[float,float]], *, mid: float, side: str, band_bps: float) -> float:
        band=float(band_bps)/10000.0
        if side=="bids":
            return sum(p*q for p,q in levels if p>=mid*(1.0-band))
        return sum(p*q for p,q in levels if p<=mid*(1.0+band))

    @staticmethod
    def _imbalance(bid_depth: Optional[float],ask_depth: Optional[float]) -> Optional[float]:
        if bid_depth is None or ask_depth is None:
            return None
        total=bid_depth+ask_depth
        return (bid_depth-ask_depth)/total if total>0 else None

    @staticmethod
    def _quote_ofi(
        previous: tuple[float,float,float,float] | None,
        current: tuple[float,float,float,float],
    ) -> Optional[float]:
        if previous is None:
            return None
        pbid,pbsize,pask,pasize=previous
        bid,bsize,ask,asize=current

        # Best-level order-flow imbalance proxy following the direction of
        # displayed-liquidity change. It is not message-level OFI.
        bid_term=(bsize if bid>=pbid else 0.0) - (pbsize if bid<=pbid else 0.0)
        ask_term=(pasize if ask>=pask else 0.0) - (asize if ask<=pask else 0.0)
        raw=bid_term+ask_term
        scale=max(1e-12,pbsize+pasize+bsize+asize)
        return max(-1.0,min(1.0,(2.0*raw)/scale))

    @staticmethod
    def _trade_metrics(trades: Iterable[dict[str,Any]]) -> tuple[float,float,int,tuple[str,...]]:
        buy=0.0
        sell=0.0
        count=0
        notes=set()
        for trade in trades or []:
            price=_finite(trade.get("price"))
            amount=_finite(trade.get("amount",trade.get("quantity")))
            if price is None or amount is None or price<=0 or amount<0:
                continue
            notional=price*amount
            side=str(trade.get("side") or "").lower()
            if side=="buy":
                buy+=notional
            elif side=="sell":
                sell+=notional
            else:
                notes.add("trade_side_unavailable")
            count+=1
        return buy,sell,count,tuple(sorted(notes))

    def build(
        self,
        *,
        symbol: str,
        timestamp_ms: int,
        orderbook: dict[str,Any],
        trades: Iterable[dict[str,Any]] = (),
        observation_window_sec: float = 1.0,
    ) -> MicrostructureSnapshot:
        bids=self._levels(orderbook or {},"bids")
        asks=self._levels(orderbook or {},"asks")
        notes=[]

        best_bid=bids[0][0] if bids else None
        best_ask=asks[0][0] if asks else None
        mid=None
        spread_bps=None
        if best_bid is not None and best_ask is not None and best_ask>=best_bid:
            mid=(best_bid+best_ask)/2.0
            spread_bps=((best_ask-best_bid)/mid)*10000.0 if mid>0 else None
        else:
            notes.append("top_of_book_unavailable")

        depths:dict[tuple[str,int],Optional[float]]={}
        if mid is not None:
            for band in (5,10,25):
                depths[("bids",band)]=self._depth(bids,mid=mid,side="bids",band_bps=band)
                depths[("asks",band)]=self._depth(asks,mid=mid,side="asks",band_bps=band)
        else:
            for band in (5,10,25):
                depths[("bids",band)]=None
                depths[("asks",band)]=None

        current_top=None
        quote_ofi=None
        if bids and asks:
            current_top=(bids[0][0],bids[0][1],asks[0][0],asks[0][1])
            quote_ofi=self._quote_ofi(self._last_top.get(symbol),current_top)
            self._last_top[symbol]=current_top
        if quote_ofi is None:
            notes.append("quote_ofi_warming")

        buy_usd,sell_usd,trade_count,trade_notes=self._trade_metrics(trades)
        notes.extend(trade_notes)
        total_trade_usd=buy_usd+sell_usd
        aggressor_imbalance=(buy_usd-sell_usd)/total_trade_usd if total_trade_usd>0 else None
        if total_trade_usd<=0:
            notes.append("aggressor_flow_unavailable")

        window=max(1e-9,float(observation_window_sec))
        intensity=trade_count/window
        counts=self._trade_counts.setdefault(symbol,deque(maxlen=self.history))
        counts.append(trade_count)

        current_depth=None
        bd25=depths[("bids",25)]
        ad25=depths[("asks",25)]
        if bd25 is not None and ad25 is not None:
            current_depth=bd25+ad25
        previous_depth=self._last_depth.get(symbol)
        recovery=None
        if current_depth is not None:
            if previous_depth is not None and previous_depth>0:
                recovery=(current_depth-previous_depth)/previous_depth
                recovery=max(-2.0,min(2.0,recovery))
            self._last_depth[symbol]=current_depth

        quality_components=[
            1.0 if mid is not None else 0.0,
            1.0 if bd25 is not None and ad25 is not None else 0.0,
            1.0 if quote_ofi is not None else 0.0,
            1.0 if total_trade_usd>0 else 0.0,
        ]
        data_quality=sum(quality_components)/len(quality_components)

        return MicrostructureSnapshot(
            schema="hivenance_relative_value_microstructure_v1",
            symbol=symbol,
            timestamp_ms=int(timestamp_ms),
            best_bid=best_bid,
            best_ask=best_ask,
            mid=mid,
            spread_bps=spread_bps,
            bid_depth_usd_5bps=depths[("bids",5)],
            ask_depth_usd_5bps=depths[("asks",5)],
            bid_depth_usd_10bps=depths[("bids",10)],
            ask_depth_usd_10bps=depths[("asks",10)],
            bid_depth_usd_25bps=bd25,
            ask_depth_usd_25bps=ad25,
            book_imbalance_25bps=self._imbalance(bd25,ad25),
            quote_ofi_proxy=quote_ofi,
            aggressor_buy_usd=buy_usd if total_trade_usd>0 else None,
            aggressor_sell_usd=sell_usd if total_trade_usd>0 else None,
            aggressor_flow_imbalance=aggressor_imbalance,
            trade_count=trade_count,
            trade_intensity_per_sec=intensity,
            depth_recovery_score=recovery,
            data_quality=round(data_quality,6),
            source_notes=tuple(sorted(set(notes))),
        )
