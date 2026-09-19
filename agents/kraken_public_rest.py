from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from typing import Any, Iterable


class KrakenPublicRestClient:
    """Small stdlib-only Kraken public REST adapter.

    Implements the CCXT-shaped methods used by ObservationSwarmAgent:
    load_markets, fetch_tickers, fetch_ticker, fetch_ohlcv and
    fetch_order_book. No authenticated/private endpoints exist in this class.
    """

    BASE_URL = "https://api.kraken.com/0/public"

    _ASSET_ALIASES = {
        "XBT": "BTC",
        "XXBT": "BTC",
        "XDG": "DOGE",
        "XXDG": "DOGE",
        "ZUSD": "USD",
        "ZEUR": "EUR",
        "ZGBP": "GBP",
        "ZJPY": "JPY",
        "ZCAD": "CAD",
        "ZAUD": "AUD",
    }

    _INTERVAL_MINUTES = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
        "1w": 10080,
    }

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = float(timeout)
        self._markets: dict[str, dict[str, Any]] = {}
        self._pair_alias_to_symbol: dict[str, str] = {}
        self._symbol_to_pair: dict[str, str] = {}

    @classmethod
    def _asset(cls, value: str) -> str:
        raw = str(value or "").upper()
        if raw in cls._ASSET_ALIASES:
            return cls._ASSET_ALIASES[raw]
        if len(raw) == 4 and raw[0] in {"X", "Z"}:
            raw = raw[1:]
        return cls._ASSET_ALIASES.get(raw, raw)

    @classmethod
    def _symbol_from_pair(cls, pair: dict[str, Any]) -> str:
        wsname = str(pair.get("wsname") or "")
        if "/" in wsname:
            base, quote = wsname.split("/", 1)
            return f"{cls._asset(base)}/{cls._asset(quote)}"
        base = cls._asset(str(pair.get("base") or ""))
        quote = cls._asset(str(pair.get("quote") or ""))
        return f"{base}/{quote}"

    def _get(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.BASE_URL}/{method}"
        if query:
            url += "?" + query
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Hivenance-Phoenix-PublicObserver/1.0",
                "Accept": "application/json",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        errors = payload.get("error") or []
        if errors:
            raise RuntimeError("Kraken public API error: " + "; ".join(map(str, errors)))
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Kraken public API returned no result mapping")
        return result

    def load_markets(self) -> dict[str, Any]:
        result = self._get("AssetPairs")
        markets: dict[str, dict[str, Any]] = {}
        aliases: dict[str, str] = {}
        reverse: dict[str, str] = {}

        for pair_key, row in result.items():
            if not isinstance(row, dict):
                continue
            symbol = self._symbol_from_pair(row)
            if "/" not in symbol or symbol.startswith("/"):
                continue
            base, quote = symbol.split("/", 1)
            status = str(row.get("status") or "online").lower()
            market = {
                "id": pair_key,
                "symbol": symbol,
                "base": base,
                "quote": quote,
                "active": status in {"online", "post_only", "limit_only"},
                "spot": True,
                "type": "spot",
                "info": row,
            }
            markets[symbol] = market
            reverse[symbol] = pair_key
            for alias in {
                pair_key,
                str(row.get("altname") or ""),
                str(row.get("wsname") or ""),
            }:
                if alias:
                    aliases[alias.upper()] = symbol

        self._markets = markets
        self._pair_alias_to_symbol = aliases
        self._symbol_to_pair = reverse
        return dict(markets)

    def _ensure_markets(self) -> None:
        if not self._markets:
            self.load_markets()

    def _pair_id(self, symbol: str) -> str:
        self._ensure_markets()
        normalized = str(symbol).upper()
        if normalized in self._symbol_to_pair:
            return self._symbol_to_pair[normalized]
        alias_symbol = self._pair_alias_to_symbol.get(normalized)
        if alias_symbol and alias_symbol in self._symbol_to_pair:
            return self._symbol_to_pair[alias_symbol]
        raise KeyError(f"Unknown Kraken symbol: {symbol}")

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
            return out if math.isfinite(out) else float(default)
        except (TypeError, ValueError):
            return float(default)

    def _ticker_row(self, api_key: str, row: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        symbol = self._pair_alias_to_symbol.get(str(api_key).upper())
        if symbol is None:
            # Kraken result keys are frequently internal pair ids.
            market = self._markets.get(str(api_key).upper())
            symbol = market.get("symbol") if isinstance(market, dict) else None
        if symbol is None:
            for candidate, market in self._markets.items():
                if str(market.get("id") or "").upper() == str(api_key).upper():
                    symbol = candidate
                    break
        if symbol is None:
            return None

        last = self._float((row.get("c") or [0])[0])
        open_ = self._float(row.get("o"))
        base_volume = self._float((row.get("v") or [0, 0])[-1])
        quote_volume = base_volume * last if last > 0 else 0.0
        percentage = ((last - open_) / open_) * 100.0 if open_ > 0 else 0.0
        return symbol, {
            "symbol": symbol,
            "last": last,
            "open": open_,
            "percentage": percentage,
            "baseVolume": base_volume,
            "quoteVolume": quote_volume,
            "bid": self._float((row.get("b") or [0])[0]),
            "ask": self._float((row.get("a") or [0])[0]),
            "info": row,
        }

    def fetch_tickers(self) -> dict[str, Any]:
        self._ensure_markets()
        # Kraken currently accepts a comma-separated pair list. Chunk to keep
        # request URLs bounded and avoid depending on undocumented no-pair behavior.
        pair_ids = list(self._symbol_to_pair.values())
        out: dict[str, Any] = {}
        chunk_size = 80
        for start in range(0, len(pair_ids), chunk_size):
            chunk = pair_ids[start:start + chunk_size]
            result = self._get("Ticker", {"pair": ",".join(chunk)})
            for key, row in result.items():
                if not isinstance(row, dict):
                    continue
                parsed = self._ticker_row(key, row)
                if parsed is not None:
                    symbol, ticker = parsed
                    out[symbol] = ticker
        return out

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        pair_id = self._pair_id(symbol)
        result = self._get("Ticker", {"pair": pair_id})
        for key, row in result.items():
            if isinstance(row, dict):
                parsed = self._ticker_row(key, row)
                if parsed is not None:
                    return parsed[1]
        raise RuntimeError(f"Kraken ticker unavailable for {symbol}")

    def fetch_ohlcv(
        self,
        symbol: str,
        *,
        timeframe: str = "1m",
        limit: int = 121,
    ) -> list[list[float]]:
        pair_id = self._pair_id(symbol)
        interval = self._INTERVAL_MINUTES.get(str(timeframe), 1)
        result = self._get("OHLC", {"pair": pair_id, "interval": interval})
        rows = None
        for key, value in result.items():
            if key == "last":
                continue
            if isinstance(value, list):
                rows = value
                break
        if rows is None:
            return []

        out: list[list[float]] = []
        for row in rows[-max(1, int(limit)):]:
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                continue
            out.append([
                int(float(row[0]) * 1000),
                self._float(row[1]),
                self._float(row[2]),
                self._float(row[3]),
                self._float(row[4]),
                self._float(row[6]),
            ])
        return out


    def fetch_trades(self, symbol: str, *, limit: int = 200) -> list[dict[str, Any]]:
        """Fetch recent public trades with normalized aggressor side."""
        pair_id = self._pair_id(symbol)
        result = self._get("Trades", {"pair": pair_id})
        rows = next((value for key, value in result.items() if key != "last" and isinstance(value, list)), [])
        out: list[dict[str, Any]] = []
        for row in rows[-max(1, int(limit)):]:
            if not isinstance(row, (list, tuple)) or len(row) < 4:
                continue
            out.append({
                "timestamp": int(self._float(row[2]) * 1000),
                "price": self._float(row[0]),
                "amount": self._float(row[1]),
                "side": "buy" if str(row[3]).lower() == "b" else "sell",
            })
        return out

    def fetch_order_book(self, symbol: str, *, limit: int = 50) -> dict[str, Any]:
        pair_id = self._pair_id(symbol)
        result = self._get("Depth", {"pair": pair_id, "count": max(1, int(limit))})
        book = next((row for row in result.values() if isinstance(row, dict)), {})
        return {
            "symbol": symbol,
            "bids": [
                [self._float(row[0]), self._float(row[1])]
                for row in (book.get("bids") or [])
                if isinstance(row, (list, tuple)) and len(row) >= 2
            ],
            "asks": [
                [self._float(row[0]), self._float(row[1])]
                for row in (book.get("asks") or [])
                if isinstance(row, (list, tuple)) and len(row) >= 2
            ],
        }
