import requests
import ccxt
import logging
import time
from binance.client import Client
from typing import Tuple, List, Optional


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

    def average_volume(self, closes: List[float]) -> float:
        """Calculate average volume from closes (placeholder, since volumes not passed)."""
        # Placeholder: return average of closes as proxy
        if closes:
            return sum(closes) / len(closes)
        return 0.0


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
        self._last_ohlcv = []
        try:
            self.client.load_markets()
        except Exception:
            pass
        self.symbol = self._resolve_symbol(self.symbol)

    def _resolve_symbol(self, symbol: str) -> str:
        try:
            markets = getattr(self.client, 'markets', None) or {}
            if symbol in markets:
                return symbol
            target = str(symbol).replace('/', '').upper()
            for m in markets.keys():
                if str(m).replace('/', '').upper() == target:
                    return m
        except Exception:
            pass
        return symbol

    def _fetch_ohlcv_with_retry(self, limit: int):
        last_err = None
        symbols = []
        for s in [self.symbol, self._resolve_symbol(self.symbol)]:
            if s and s not in symbols:
                symbols.append(s)
        for sym in symbols:
            for attempt in range(3):
                try:
                    ohlcv = self.client.fetch_ohlcv(sym, timeframe=self.interval, limit=limit)
                    if ohlcv:
                        self._last_ohlcv = ohlcv
                        self.symbol = sym
                        return ohlcv
                except Exception as e:
                    last_err = e
                time.sleep(0.2 * (attempt + 1))
        if self._last_ohlcv:
            return self._last_ohlcv[-limit:]
        if last_err:
            logging.warning(f"Kraken OHLCV fetch failed for {self.symbol}: {last_err}")
        return []

    def fetch_closes(self, limit: int) -> Tuple[List[int], List[float]]:
        ohlcv = self._fetch_ohlcv_with_retry(limit)
        close_times = [int(c[0]) for c in ohlcv]
        closes = [float(c[4]) for c in ohlcv]
        return close_times, closes

    def fetch_volumes(self, limit: int) -> List[float]:
        ohlcv = self._fetch_ohlcv_with_retry(limit)
        return [float(c[5]) for c in ohlcv]

    def fetch_latest_price(self) -> float:
        try:
            ticker = self.client.fetch_ticker(self.symbol)
            return float(ticker["last"])
        except Exception:
            if self._last_ohlcv:
                return float(self._last_ohlcv[-1][4])
            raise

    def average_volume(self, closes: List[float]) -> float:
        if closes:
            return sum(closes) / len(closes)
        return 0.0


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
        # Placeholder: return random or fixed value
        # In real: fetch from API
        return 0.5  # Neutral sentiment score -1 to 1


class TrendAnalysis:
    """
    Basic trend analysis.
    """
    @staticmethod
    def is_uptrend(closes: List[float]) -> bool:
        if len(closes) < 2:
            return False
        return closes[-1] > closes[0]

    @staticmethod
    def average_volume(volumes: List[float]) -> float:
        return sum(volumes) / len(volumes) if volumes else 0
