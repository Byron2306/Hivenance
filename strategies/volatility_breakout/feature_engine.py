from __future__ import annotations

import math
import statistics
import time
from typing import Any, Iterable, Optional, Sequence

from .models import FeatureVector


def _float(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _returns(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for previous, current in zip(values, values[1:]):
        if previous > 0:
            out.append((current - previous) / previous)
    return out


def _pstdev(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    return float(statistics.pstdev(values))


def _zscore(value: float, baseline: Sequence[float]) -> Optional[float]:
    if len(baseline) < 5:
        return None
    mean = statistics.fmean(baseline)
    std = statistics.pstdev(baseline)
    if std <= 0:
        return 0.0 if value == mean else None
    return float((value - mean) / std)


def _linear_slope(values: Sequence[float]) -> Optional[float]:
    if len(values) < 3:
        return None
    n = len(values)
    mean_x = (n - 1) / 2.0
    mean_y = statistics.fmean(values)
    denom = sum((i - mean_x) ** 2 for i in range(n))
    if denom <= 0 or mean_y == 0:
        return None
    slope = sum((i - mean_x) * (value - mean_y) for i, value in enumerate(values)) / denom
    return float(slope / mean_y)


def _classify_regime(
    *,
    volatility_expansion: Optional[float],
    trend_slope: Optional[float],
    range_position: Optional[float],
    volume_zscore: Optional[float],
    spread_bps: Optional[float],
    depth_usd_25bps: Optional[float],
    return_zscore: Optional[float],
) -> dict[str, Any]:
    vol = float(volatility_expansion or 0.0)
    trend = float(trend_slope or 0.0)
    volume = float(volume_zscore or 0.0)
    ret_z = float(return_zscore or 0.0)
    spread = float(spread_bps or 0.0)
    depth = float(depth_usd_25bps or 0.0)
    range_pos = range_position if range_position is not None else 0.5

    if vol >= 1.35 and abs(trend) >= 0.000003:
        regime = 'trend_expansion'
    elif vol >= 1.20 and (range_pos >= 0.85 or range_pos <= 0.15) and abs(ret_z) >= 1.0:
        regime = 'stretch_exhaustion'
    elif spread > 12.0 or depth < 250_000.0:
        regime = 'hostile_liquidity'
    elif abs(trend) < 0.000001 and 0.25 <= range_pos <= 0.75 and vol <= 0.85:
        regime = 'quiet_range'
    else:
        regime = 'balanced_transition'

    trend_direction = 'up' if trend > 0 else 'down' if trend < 0 else 'flat'
    liquidity_state = 'deep' if depth >= 1_000_000.0 and spread <= 5.0 else 'fragile' if spread > 12.0 or depth < 250_000.0 else 'normal'
    participation_state = 'expanding' if volume >= 1.0 else 'soft' if volume <= -0.5 else 'normal'

    return {
        'regime_hint': regime,
        'trend_direction': trend_direction,
        'liquidity_state': liquidity_state,
        'participation_state': participation_state,
        'confidence': round(
            max(
                0.2,
                min(
                    0.95,
                    0.45
                    + min(0.2, abs(trend) * 20_000.0)
                    + min(0.15, abs(vol - 1.0) * 0.35)
                    + min(0.15, abs(ret_z) * 0.05),
                ),
            ),
            3,
        ),
    }


def _true_ranges(rows: Sequence[Sequence[Any]]) -> list[float]:
    out: list[float] = []
    previous_close: Optional[float] = None
    for row in rows:
        if len(row) < 6:
            continue
        high = _float(row[2])
        low = _float(row[3])
        close = _float(row[4])
        if high is None or low is None or close is None or high < low:
            continue
        candidates = [high - low]
        if previous_close is not None:
            candidates.extend([abs(high - previous_close), abs(low - previous_close)])
        out.append(max(candidates))
        previous_close = close
    return out


def _interval_ms(timeframe: str) -> int:
    unit = (timeframe or '1m')[-1:].lower()
    try:
        count = int((timeframe or '1m')[:-1])
    except ValueError:
        count = 1
    multipliers = {'s': 1_000, 'm': 60_000, 'h': 3_600_000, 'd': 86_400_000}
    return max(1_000, count * multipliers.get(unit, 60_000))


class Phase1FeatureEngine:
    """Builds observation features without inventing values for unavailable data."""

    def __init__(
        self,
        *,
        timeframe: str = '1m',
        short_window: int = 5,
        baseline_window: int = 60,
        stale_after_sec: int = 180,
        depth_band_bps: float = 25.0,
    ) -> None:
        if short_window < 2 or baseline_window <= short_window:
            raise ValueError('baseline_window must be larger than short_window')
        self.timeframe = timeframe
        self.short_window = short_window
        self.baseline_window = baseline_window
        self.stale_after_sec = max(1, int(stale_after_sec))
        self.depth_band_bps = max(1.0, float(depth_band_bps))

    @staticmethod
    def _book_metrics(orderbook: dict[str, Any], depth_band_bps: float = 25.0) -> tuple[Optional[float], Optional[float], Optional[float]]:
        bids = orderbook.get('bids') or []
        asks = orderbook.get('asks') or []
        if not bids or not asks:
            return None, None, None
        bid = _float(bids[0][0])
        ask = _float(asks[0][0])
        if bid is None or ask is None or bid <= 0 or ask <= bid:
            return None, None, None
        mid = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / mid) * 10_000.0
        band = max(1.0, float(depth_band_bps)) / 10_000.0
        bid_depth = sum(
            (price or 0.0) * (amount or 0.0)
            for raw_price, raw_amount, *_ in bids
            if (price := _float(raw_price)) is not None
            and (amount := _float(raw_amount)) is not None
            and price >= mid * (1.0 - band)
        )
        ask_depth = sum(
            (price or 0.0) * (amount or 0.0)
            for raw_price, raw_amount, *_ in asks
            if (price := _float(raw_price)) is not None
            and (amount := _float(raw_amount)) is not None
            and price <= mid * (1.0 + band)
        )
        total_depth = bid_depth + ask_depth
        imbalance = ((bid_depth - ask_depth) / total_depth) if total_depth > 0 else None
        return spread_bps, total_depth, imbalance

    def build(
        self,
        *,
        symbol: str,
        ohlcv: Sequence[Sequence[Any]],
        orderbook: dict[str, Any],
        ticker: dict[str, Any],
        observed_at_ms: Optional[int] = None,
    ) -> FeatureVector:
        now_ms = int(observed_at_ms or time.time() * 1000)
        rows = [row for row in (ohlcv or []) if len(row) >= 6]
        timestamps = [int(row[0]) for row in rows if _float(row[0]) is not None]
        closes = [float(row[4]) for row in rows if _float(row[4]) is not None and float(row[4]) > 0]
        highs = [float(row[2]) for row in rows if _float(row[2]) is not None and float(row[2]) > 0]
        lows = [float(row[3]) for row in rows if _float(row[3]) is not None and float(row[3]) > 0]
        volumes = [float(row[5]) for row in rows if _float(row[5]) is not None and float(row[5]) >= 0]

        price = _float(ticker.get('last')) or (closes[-1] if closes else None)
        quote_volume = _float(ticker.get('quoteVolume'))
        if quote_volume is None:
            base_volume = _float(ticker.get('baseVolume'))
            if base_volume is not None and price is not None:
                quote_volume = base_volume * price

        fast_returns = _returns(closes[-(self.short_window + 1):])
        baseline_returns = _returns(closes[-(self.baseline_window + 1):])
        fast_vol = _pstdev(fast_returns)
        baseline_vol = _pstdev(baseline_returns)
        expansion = None
        if fast_vol is not None and baseline_vol is not None and baseline_vol > 0:
            expansion = max(0.0, min(20.0, fast_vol / baseline_vol))

        volume_zscore = None
        if len(volumes) >= self.baseline_window:
            recent = statistics.fmean(volumes[-self.short_window:])
            baseline = volumes[-self.baseline_window:-self.short_window]
            volume_zscore = _zscore(recent, baseline)

        return_5 = None
        if len(closes) > self.short_window and closes[-(self.short_window + 1)] > 0:
            return_5 = (closes[-1] - closes[-(self.short_window + 1)]) / closes[-(self.short_window + 1)]

        return_zscore = None
        if len(closes) >= self.baseline_window + self.short_window + 1:
            rolling_short_returns: list[float] = []
            start = max(self.short_window, len(closes) - self.baseline_window - self.short_window)
            for index in range(start, len(closes) - self.short_window):
                prior = closes[index - self.short_window]
                if prior > 0:
                    rolling_short_returns.append((closes[index] - prior) / prior)
            if return_5 is not None and rolling_short_returns:
                return_zscore = _zscore(return_5, rolling_short_returns)

        price_zscore = None
        if len(closes) >= self.baseline_window:
            baseline_prices = closes[-self.baseline_window:]
            price_zscore = _zscore(closes[-1], baseline_prices[:-1]) if len(baseline_prices) > 5 else None

        range_position = None
        if highs and lows and len(highs) >= self.baseline_window and len(lows) >= self.baseline_window and price is not None:
            window_high = max(highs[-self.baseline_window:])
            window_low = min(lows[-self.baseline_window:])
            if window_high > window_low:
                range_position = max(0.0, min(1.0, (price - window_low) / (window_high - window_low)))

        trend_window = closes[-max(self.short_window * 2, 10):]
        trend_slope = _linear_slope(trend_window)
        returns_recent = _returns(closes[-(self.short_window + 1):])
        reversal_return_1 = returns_recent[-1] if returns_recent else None
        momentum_consistency = None
        if returns_recent and return_5 not in (None, 0.0):
            direction = 1.0 if return_5 > 0 else -1.0
            momentum_consistency = sum(1 for value in returns_recent if value * direction > 0) / len(returns_recent)

        volume_ratio = None
        if len(volumes) >= self.baseline_window:
            recent_volume = statistics.fmean(volumes[-self.short_window:])
            historical_volume = volumes[-self.baseline_window:-self.short_window]
            if historical_volume:
                baseline_volume = statistics.fmean(historical_volume)
                if baseline_volume > 0:
                    volume_ratio = recent_volume / baseline_volume

        true_ranges = _true_ranges(rows[-15:])
        atr_pct = None
        if true_ranges and price is not None and price > 0:
            atr_pct = statistics.fmean(true_ranges[-14:]) / price

        spread_bps, depth_usd_25bps, book_imbalance = self._book_metrics(orderbook or {}, self.depth_band_bps)

        freshness_sec = None
        if timestamps:
            freshness_sec = max(0.0, (now_ms - timestamps[-1]) / 1000.0)

        continuity_ratio = None
        if len(timestamps) >= 2:
            expected = _interval_ms(self.timeframe)
            valid = sum(1 for a, b in zip(timestamps, timestamps[1:]) if 0 < (b - a) <= expected * 1.5)
            continuity_ratio = valid / max(1, len(timestamps) - 1)

        quality_parts = {
            'price': 1.0 if price is not None and price > 0 else 0.0,
            'ohlcv_depth': min(1.0, len(rows) / max(1, self.baseline_window + 1)),
            'volume_depth': min(1.0, len(volumes) / max(1, self.baseline_window)),
            'orderbook': 1.0 if spread_bps is not None and depth_usd_25bps is not None else 0.0,
            'freshness': 1.0 if freshness_sec is not None and freshness_sec <= self.stale_after_sec else 0.0,
            'continuity': float(continuity_ratio or 0.0),
        }
        weights = {
            'price': 0.10,
            'ohlcv_depth': 0.25,
            'volume_depth': 0.15,
            'orderbook': 0.20,
            'freshness': 0.15,
            'continuity': 0.15,
        }
        data_quality = sum(quality_parts[key] * weights[key] for key in weights)
        complete = bool(
            price is not None
            and fast_vol is not None
            and baseline_vol is not None
            and spread_bps is not None
            and depth_usd_25bps is not None
            and freshness_sec is not None
            and freshness_sec <= self.stale_after_sec
            and (continuity_ratio or 0.0) >= 0.95
        )
        regime_inputs = _classify_regime(
            volatility_expansion=expansion,
            trend_slope=trend_slope,
            range_position=range_position,
            volume_zscore=volume_zscore,
            spread_bps=spread_bps,
            depth_usd_25bps=depth_usd_25bps,
            return_zscore=return_zscore,
        )

        return FeatureVector(
            symbol=symbol,
            timestamp_ms=now_ms,
            price=price,
            realized_volatility_fast=fast_vol,
            realized_volatility_baseline=baseline_vol,
            volatility_expansion=expansion,
            volume_zscore=volume_zscore,
            trade_count_zscore=None,
            order_flow_imbalance=None,
            book_imbalance=book_imbalance,
            spread_bps=spread_bps,
            depth_usd_25bps=depth_usd_25bps,
            quote_volume_24h=quote_volume,
            return_5=return_5,
            freshness_sec=freshness_sec,
            continuity_ratio=continuity_ratio,
            data_quality=round(max(0.0, min(1.0, data_quality)), 6),
            values={
                'quality_parts': quality_parts,
                'ohlcv_rows': len(rows),
                'latest_candle_ts': timestamps[-1] if timestamps else None,
                'book_imbalance_is_proxy': True,
                'order_flow_imbalance_status': 'UNAVAILABLE_REQUIRES_SEQUENTIAL_TRADE_OR_BOOK_DELTAS',
                'trade_count_zscore_status': 'UNAVAILABLE_REQUIRES_TRADE_COUNT_HISTORY',
                'feature_version': 'phase2.v1',
                'regime_inputs': regime_inputs,
            },
            complete=complete,
            return_zscore=return_zscore,
            price_zscore=price_zscore,
            range_position=range_position,
            trend_slope=trend_slope,
            atr_pct=atr_pct,
            reversal_return_1=reversal_return_1,
            momentum_consistency=momentum_consistency,
            volume_ratio=volume_ratio,
        )

    def unavailable(self, symbol: str, timestamp_ms: int) -> FeatureVector:
        return FeatureVector(
            symbol=symbol,
            timestamp_ms=timestamp_ms,
            price=None,
            realized_volatility_fast=None,
            realized_volatility_baseline=None,
            volatility_expansion=None,
            volume_zscore=None,
            trade_count_zscore=None,
            order_flow_imbalance=None,
            book_imbalance=None,
            spread_bps=None,
            depth_usd_25bps=None,
            quote_volume_24h=None,
            return_5=None,
            freshness_sec=None,
            continuity_ratio=None,
            data_quality=0.0,
            values={'status': 'UNAVAILABLE'},
            complete=False,
        )


# Compatibility alias for earlier imports.
Phase0FeatureEngine = Phase1FeatureEngine
