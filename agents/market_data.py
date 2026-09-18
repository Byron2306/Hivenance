import math
import requests
import ccxt
import logging
from binance.client import Client
from typing import Tuple, List, Optional, Dict, Any


class MarketData:
    def __init__(self, client: Client, symbol: str, interval: str):
        self.client = client
        self.symbol = symbol
        self.interval = interval

    def fetch_closes(self, limit: int) -> Tuple[List[int], List[float]]:
        """
        Fetch recent klines and return (close_times, closes).
        Kline format: [
          [ open_time, open, high, low, close, volume, close_time, ... ],
          ...
        ]
        """
        klines = self.client.get_klines(symbol=self.symbol, interval=self.interval, limit=limit)
        close_times = [int(k[6]) for k in klines]   # close_time
        closes = [float(k[4]) for k in klines]      # close
        return close_times, closes

    def fetch_volumes(self, limit: int) -> List[float]:
        """
        Fetch recent volumes.
        """
        klines = self.client.get_klines(symbol=self.symbol, interval=self.interval, limit=limit)
        volumes = [float(k[5]) for k in klines]      # volume
        return volumes

    def fetch_latest_price(self) -> float:
        ticker = self.client.get_symbol_ticker(symbol=self.symbol)
        return float(ticker["price"])

    def fetch_orderbook(self, limit: int = 5) -> Dict[str, Any]:
        book = self.client.get_order_book(symbol=self.symbol, limit=limit)
        bids = [[float(p), float(q)] for p, q in (book.get("bids") or [])[:limit]]
        asks = [[float(p), float(q)] for p, q in (book.get("asks") or [])[:limit]]
        return self._book_payload(bids, asks)

    def average_volume(self, volumes: List[float]) -> float:
        """Calculate average volume from actual volume samples."""
        return sum(volumes) / len(volumes) if volumes else 0.0

    def _book_payload(self, bids: List[List[float]], asks: List[List[float]]) -> Dict[str, Any]:
        bid = bids[0][0] if bids else None
        ask = asks[0][0] if asks else None
        spread = ((ask - bid) / bid) if bid and ask and bid > 0 else None
        mid = ((bid + ask) / 2.0) if bid and ask else None
        top_qty = sum(q for _, q in bids[:3]) + sum(q for _, q in asks[:3])
        return {
            "symbol": self.symbol,
            "bids": bids,
            "asks": asks,
            "bid": bid,
            "ask": ask,
            "spread_pct": spread,
            "mid_price": mid,
            "top_of_book_depth_usd": (top_qty * mid) if mid else None,
        }


class KrakenMarketData:
    """
    Market data adapter for Kraken via ccxt.
    """
    INTERVAL_MAP = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }

    def __init__(self, client: ccxt.kraken, symbol: str, interval: str):
        self.client = client
        self.symbol = symbol
        self.interval = self.INTERVAL_MAP.get(interval, "1m")
        try:
            self.client.load_markets()
        except Exception:
            pass

    def fetch_closes(self, limit: int) -> Tuple[List[int], List[float]]:
        ohlcv = self.client.fetch_ohlcv(self.symbol, timeframe=self.interval, limit=limit)
        close_times = [int(c[0]) for c in ohlcv]
        closes = [float(c[4]) for c in ohlcv]
        return close_times, closes

    def fetch_volumes(self, limit: int) -> List[float]:
        ohlcv = self.client.fetch_ohlcv(self.symbol, timeframe=self.interval, limit=limit)
        return [float(c[5]) for c in ohlcv]

    def fetch_latest_price(self) -> float:
        ticker = self.client.fetch_ticker(self.symbol)
        return float(ticker["last"])

    def fetch_orderbook(self, limit: int = 5) -> Dict[str, Any]:
        book = self.client.fetch_order_book(self.symbol, limit=limit)
        bids = [[float(p), float(q)] for p, q in (book.get("bids") or [])[:limit]]
        asks = [[float(p), float(q)] for p, q in (book.get("asks") or [])[:limit]]
        bid = bids[0][0] if bids else None
        ask = asks[0][0] if asks else None
        spread = ((ask - bid) / bid) if bid and ask and bid > 0 else None
        mid = ((bid + ask) / 2.0) if bid and ask else None
        top_qty = sum(q for _, q in bids[:3]) + sum(q for _, q in asks[:3])
        return {
            "symbol": self.symbol,
            "bids": bids,
            "asks": asks,
            "bid": bid,
            "ask": ask,
            "spread_pct": spread,
            "mid_price": mid,
            "top_of_book_depth_usd": (top_qty * mid) if mid else None,
        }

    def average_volume(self, volumes: List[float]) -> float:
        return sum(volumes) / len(volumes) if volumes else 0.0


class CoinGeckoData:
    """
    Optional sanity-check spot price from CoinGecko.
    Note: CoinGecko uses coin ids; mapping symbols robustly is non-trivial.
    This example supports a few common coins.
    """
    SYMBOL_TO_COINGECKO_ID = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "ADA": "cardano",
        "XRP": "ripple",
        "DOGE": "dogecoin",
    }

    def __init__(self):
        self.base_url = "https://api.coingecko.com/api/v3"

    def spot_price_usd(self, base_symbol: str) -> Optional[float]:
        coin_id = self.SYMBOL_TO_COINGECKO_ID.get(base_symbol.upper())
        if not coin_id:
            return None
        url = f"{self.base_url}/simple/price"
        try:
            r = requests.get(
                url,
                params={
                    "ids": coin_id,
                    "vs_currencies": "usd",
                    "include_24hr_vol": "true",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            return data[coin_id]
        except Exception as e:
            # CoinGecko often rate-limits (429). Treat as optional and return None.
            logging.warning(f"CoinGecko price fetch failed: {e}")
            return None

    def market_cap_usd(self, base_symbol: str) -> Optional[float]:
        data = self.spot_price_usd(base_symbol)
        return data.get("usd_market_cap") if data else None

    def volume_24h_usd(self, base_symbol: str) -> Optional[float]:
        data = self.spot_price_usd(base_symbol)
        return data.get("usd_24h_vol") if data else None

    def price_change_24h(self, base_symbol: str) -> Optional[float]:
        data = self.spot_price_usd(base_symbol)
        return data.get("usd_24h_change") if data else None


class SentimentData:
    """
    Simple sentiment analysis. Placeholder for real implementation.
    Could integrate with Twitter API or sentiment APIs.
    """
    def __init__(self):
        self.base_url = "https://api.lunarcrush.com/v1"  # Example, requires API key

    def get_sentiment(self, symbol: str) -> Optional[float]:
        # No provider is configured. Missing data must remain missing rather than
        # masquerading as a neutral observation.
        return None


class TrendAnalysis:
    """
    Lightweight market context helpers used by the oracle, council and guards.
    """
    @staticmethod
    def returns(closes: List[float], lookback: int = 1) -> List[float]:
        if not closes or lookback <= 0 or len(closes) <= lookback:
            return []
        out = []
        for i in range(lookback, len(closes)):
            prev = float(closes[i - lookback])
            curr = float(closes[i])
            if prev > 0:
                out.append((curr - prev) / prev)
        return out

    @staticmethod
    def realized_volatility(closes: List[float], window: int = 30) -> float:
        vals = TrendAnalysis.returns((closes or [])[-(window + 1):], 1)
        if len(vals) < 2:
            return 0.0
        mean = sum(vals) / len(vals)
        var = sum((r - mean) ** 2 for r in vals) / len(vals)
        return math.sqrt(var)

    @staticmethod
    def volatility_expansion(closes: List[float], fast: int = 12, slow: int = 48) -> float:
        if len(closes or []) < slow + 1:
            return 0.0
        fast_vol = TrendAnalysis.realized_volatility(closes, fast)
        slow_vol = TrendAnalysis.realized_volatility(closes, slow)
        if slow_vol <= 0:
            return 0.0
        return max(0.0, min(5.0, fast_vol / slow_vol))

    @staticmethod
    def volume_surge(volumes: List[float], fast: int = 5, slow: int = 30) -> float:
        if len(volumes or []) < slow:
            return 0.0
        fast_avg = sum(float(v) for v in volumes[-fast:]) / max(1, fast)
        slow_avg = sum(float(v) for v in volumes[-slow:]) / max(1, slow)
        if slow_avg <= 0:
            return 0.0
        return max(0.0, min(5.0, fast_avg / slow_avg))

    @staticmethod
    def short_return(closes: List[float], lookback: int = 5) -> float:
        if len(closes or []) <= lookback:
            return 0.0
        start = float(closes[-(lookback + 1)])
        end = float(closes[-1])
        return (end - start) / max(1e-9, start)

    @staticmethod
    def max_drawdown(closes: List[float], window: int = 60) -> float:
        vals = [float(c) for c in (closes or [])[-window:] if float(c) > 0]
        if not vals:
            return 0.0
        peak = vals[0]
        worst = 0.0
        for v in vals:
            peak = max(peak, v)
            worst = min(worst, (v - peak) / max(1e-9, peak))
        return abs(worst)

    @staticmethod
    def market_context(closes: List[float], volumes: Optional[List[float]] = None) -> Dict[str, Any]:
        volumes = volumes or []
        vol = TrendAnalysis.realized_volatility(closes, 30)
        vol_exp = TrendAnalysis.volatility_expansion(closes)
        vol_surge = TrendAnalysis.volume_surge(volumes)
        ret_5 = TrendAnalysis.short_return(closes, 5)
        ret_15 = TrendAnalysis.short_return(closes, 15)
        drawdown = TrendAnalysis.max_drawdown(closes, 60)
        return {
            "realized_volatility": vol,
            "volatility_expansion": vol_exp,
            "volume_surge": vol_surge,
            "return_5": ret_5,
            "return_15": ret_15,
            "max_drawdown": drawdown,
            "is_pump": bool(ret_5 > 0.02 and vol_surge >= 1.5),
            "is_dump": bool(ret_5 < -0.02 and vol_surge >= 1.5),
            "is_tradeable_volatility": bool(vol_exp >= 1.15 and vol_surge >= 0.8),
        }

    @staticmethod
    def is_uptrend(closes: List[float]) -> bool:
        if len(closes) < 2:
            return False
        return closes[-1] > closes[0]

    @staticmethod
    def average_volume(volumes: List[float]) -> float:
        return sum(volumes) / len(volumes) if volumes else 0
