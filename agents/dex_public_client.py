"""Read-only ccxt-compatible market-data adapter backed by ``DexMarginOracle``.

Purpose
-------
``ObservationSwarmAgent`` (Phase 1) and, by extension, ``HypothesisSwarmAgent``
(Phase 2) are written against a small, generic client interface --
``load_markets`` / ``fetch_tickers`` / ``fetch_ticker`` / ``fetch_ohlcv`` /
``fetch_order_book`` -- the same shape CCXT exchange objects expose. Neither
class contains any exchange-specific logic; all statistics (realized
volatility, volume z-score, spread/depth, data quality, regime hints, etc.)
are computed generically from whatever OHLCV/orderbook/ticker data the client
returns.

This adapter implements that exact interface for the curated on-chain token
universe, so the *same* Phase 1/2 pipeline classes used for Kraken can run,
unmodified, against DEX tokens. It never touches a wallet and never submits
an order -- it only performs public read requests, the same safety posture
as ``DexMarginOracle`` itself.

Data sources (all keyless, public):
  - DexScreener token-pairs endpoint for current price/liquidity/volume,
    via ``DexMarginOracle._dexscreener_pool``.
  - GeckoTerminal per-pool OHLCV candles for realized-volatility history.
  - The existing DexMarginOracle aggregator round-trip quote (1inch /
    ParaSwap / KyberSwap fallback chain) for a documented, price-impact
    derived order-book *approximation*.

Important caveat
-----------------
AMM pools do not have a discrete limit order book. ``fetch_order_book``
below returns a single synthetic bid/ask level whose depth is derived by
linearly scaling the *measured* round-trip price impact (from a real
aggregator quote) out to the 25bps band the feature engine expects. This is
a documented proxy for "how much can I trade before moving the price by
25bps", not a real book, and should be read as such by anyone inspecting
``observation_snapshots`` rows tagged with a ``dex_*`` venue.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from agents.dex_margin_oracle import DexMarginOracle

# Maps CCXT-style timeframe strings to GeckoTerminal's ohlcv path + aggregate param.
_GECKOTERMINAL_TIMEFRAMES: Dict[str, Tuple[str, int]] = {
    "1m": ("minute", 1),
    "3m": ("minute", 3),
    "5m": ("minute", 5),
    "15m": ("minute", 15),
    "30m": ("minute", 30),
    "1h": ("hour", 1),
    "4h": ("hour", 4),
    "1d": ("day", 1),
}


class DexPublicClient:
    """CCXT-shaped, read-only client for the curated on-chain token universe."""

    def __init__(self, cfg: Any, oracle: Optional[DexMarginOracle] = None, quote_symbol: str = "USD") -> None:
        self.cfg = cfg
        self.oracle = oracle or DexMarginOracle(cfg)
        self.quote_symbol = str(quote_symbol or "USD").upper()
        self.timeout = float(getattr(cfg, "dex_oracle_timeout_sec", 8) or 8)
        self._ohlcv_cache: Dict[str, Tuple[float, List[List[float]]]] = {}

    # -- symbol helpers ---------------------------------------------------
    def _symbol(self, base: str) -> str:
        return f"{str(base).upper()}/{self.quote_symbol}"

    def _tokens(self) -> List[Dict[str, Any]]:
        return self.oracle.token_universe()

    def _token_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        base = str(symbol).split("/", 1)[0].upper()
        for token in self._tokens():
            if token["symbol"] == base:
                return token
        return None

    # -- CCXT-shaped interface ---------------------------------------------
    def load_markets(self) -> Dict[str, Any]:
        markets: Dict[str, Any] = {}
        for token in self._tokens():
            symbol = self._symbol(token["symbol"])
            markets[symbol] = {
                "symbol": symbol,
                "base": token["symbol"],
                "quote": self.quote_symbol,
                "active": True,
                "type": "spot",
                "spot": True,
                "info": {"address": token["address"], "chain": self.oracle.chain_slug},
            }
        return markets

    def _ticker_for_token(self, token: Dict[str, Any]) -> Dict[str, Any]:
        pool = self.oracle._dexscreener_pool(token["address"])
        price = pool.get("price_usd")
        pct24 = pool.get("price_change_h24_pct")
        open_price = None
        if price is not None and pct24 is not None and (1.0 + pct24 / 100.0) != 0:
            open_price = price / (1.0 + pct24 / 100.0)
        base_volume = None
        volume_24h = pool.get("volume_24h_usd")
        if volume_24h is not None and price:
            base_volume = volume_24h / price
        return {
            "symbol": self._symbol(token["symbol"]),
            "last": price,
            "open": open_price,
            "percentage": pct24,
            "quoteVolume": volume_24h,
            "baseVolume": base_volume,
            "info": pool,
        }

    def fetch_tickers(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for token in self._tokens():
            try:
                out[self._symbol(token["symbol"])] = self._ticker_for_token(token)
            except Exception:
                continue
        return out

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        token = self._token_for_symbol(symbol)
        if token is None:
            raise ValueError(f"unknown DEX symbol {symbol!r}")
        return self._ticker_for_token(token)

    def fetch_ohlcv(self, symbol: str, timeframe: str = "15m", limit: int = 121) -> List[List[float]]:
        token = self._token_for_symbol(symbol)
        if token is None:
            return []
        pool = self.oracle._dexscreener_pool(token["address"])
        pair = pool.get("pair_address")
        if not pair:
            return []
        gecko_tf, aggregate = _GECKOTERMINAL_TIMEFRAMES.get(str(timeframe), ("minute", 15))
        cache_key = f"{pair}:{gecko_tf}:{aggregate}"
        ttl = float(getattr(self.cfg, "dex_phase1_ohlcv_cache_sec", 120) or 120)
        cached = self._ohlcv_cache.get(cache_key)
        if cached and time.time() - cached[0] < ttl:
            return list(cached[1])
        url = f"https://api.geckoterminal.com/api/v2/networks/{self.oracle.chain_slug}/pools/{pair}/ohlcv/{gecko_tf}"
        rows: List[Any] = []
        try:
            resp = requests.get(
                url,
                params={"aggregate": aggregate, "limit": min(int(limit), 1000), "currency": "usd"},
                timeout=self.timeout,
                headers={"accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            rows = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        except Exception:
            rows = []
        candles: List[List[float]] = []
        for row in rows:
            if len(row) < 6:
                continue
            ts_sec, o, h, l, c, v = row[:6]
            try:
                candles.append([int(float(ts_sec) * 1000), float(o), float(h), float(l), float(c), float(v)])
            except (TypeError, ValueError):
                continue
        candles.sort(key=lambda r: r[0])
        candles = candles[-int(limit):]
        self._ohlcv_cache[cache_key] = (time.time(), candles)
        return candles

    def fetch_order_book(self, symbol: str, limit: int = 50) -> Dict[str, Any]:
        book: Dict[str, Any] = {"bids": [], "asks": []}
        token = self._token_for_symbol(symbol)
        if token is None:
            return book
        probe_amount = float(getattr(self.cfg, "dex_probe_amount_usd", 25.0) or 25.0)
        analysis = self.oracle.analyze_token(token, amount_usd=probe_amount, quote_symbol=self.quote_symbol)
        pool = analysis.get("pool") or {}
        quality = analysis.get("quality") or {}
        price = pool.get("price_usd")
        if not price or price <= 0:
            return book
        price_impact = quality.get("price_impact_pct")  # fraction (e.g. 0.0006), or None if quote failed
        liquidity_usd = quality.get("liquidity_usd")
        if price_impact and price_impact > 0:
            # Linear scaling: if trading `probe_amount` moved the price by
            # `price_impact`, then the size that moves it by 25bps is
            # probe_amount * (0.0025 / price_impact).
            depth_usd_25bps = probe_amount * (0.0025 / price_impact)
        else:
            depth_usd_25bps = float(getattr(self.cfg, "dex_min_liquidity_usd", 50000) or 50000) * 0.05
        if liquidity_usd:
            depth_usd_25bps = max(0.0, min(depth_usd_25bps, float(liquidity_usd)))
        half_spread_bps = max(1.0, float(price_impact or 0.0005) * 10000.0)
        bid_price = price * (1.0 - half_spread_bps / 20000.0)
        ask_price = price * (1.0 + half_spread_bps / 20000.0)
        bid_qty = (depth_usd_25bps / 2.0) / bid_price if bid_price > 0 else 0.0
        ask_qty = (depth_usd_25bps / 2.0) / ask_price if ask_price > 0 else 0.0
        book["bids"] = [[bid_price, bid_qty]]
        book["asks"] = [[ask_price, ask_qty]]
        return book
