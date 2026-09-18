"""Live Kraken Futures perpetual public market-data observer.

This is the real-data counterpart to the ``kraken_spot_price_proxy_pending_
futures_feed`` fallback used throughout ``derivatives_trend_lab.py``. It
fetches PUBLIC-ONLY market data (ticker, order book, funding rate) for the
configured perpetual symbols via ccxt's ``krakenfutures`` client and persists
snapshots into the existing ``observation_snapshots`` table, tagged with
``venue="kraken_futures"`` so they never mix with the spot proxy rows.

No API keys, no authenticated endpoints, no order placement anywhere in this
module. ``execution_wired`` is always false and ``orders_submitted`` is
always 0, matching the rest of the Phase-1/Phase-2 research pipeline.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

# Canonical (spot-style) symbol -> ccxt unified Kraken Futures perpetual symbol.
DEFAULT_PERPETUAL_SYMBOL_MAP: dict[str, str] = {
    "BTC/USD": "BTC/USD:USD",
    "ETH/USD": "ETH/USD:USD",
    "SOL/USD": "SOL/USD:USD",
}


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def perpetual_symbol_map(cfg: Any) -> dict[str, str]:
    raw = getattr(cfg, "derivatives_trend_perpetual_symbol_map", None)
    if isinstance(raw, dict) and raw:
        return {str(key): str(value) for key, value in raw.items()}
    return dict(DEFAULT_PERPETUAL_SYMBOL_MAP)


def ensure_schema(conn: Any) -> None:
    """Defensive create -- normally already created by ``DataStoreAgent``."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observation_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            ts REAL,
            venue TEXT,
            symbol TEXT,
            price REAL,
            quote_volume_24h REAL,
            spread_bps REAL,
            depth_usd_25bps REAL,
            volatility_expansion REAL,
            volume_zscore REAL,
            book_imbalance REAL,
            data_quality REAL,
            observation_eligible INTEGER,
            execution_eligible INTEGER DEFAULT 0,
            rejection_reasons TEXT,
            payload TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_observation_symbol_ts ON observation_snapshots(symbol, ts)")
    conn.commit()


def build_public_krakenfutures_client() -> Any:
    """Public-only ccxt Kraken Futures client. No keys, no private endpoints."""
    import ccxt

    return ccxt.krakenfutures({"enableRateLimit": True, "timeout": 20_000})


def _snapshot_for_symbol(client: Any, canonical_symbol: str, perp_symbol: str) -> dict[str, Any]:
    ticker = client.fetch_ticker(perp_symbol)
    orderbook = client.fetch_order_book(perp_symbol, limit=10)
    funding: dict[str, Any] | None = None
    if hasattr(client, "fetch_funding_rate"):
        try:
            funding = client.fetch_funding_rate(perp_symbol)
        except Exception:
            funding = None

    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []
    bid = _float(bids[0][0]) if bids else None
    ask = _float(asks[0][0]) if asks else None
    last = _float(ticker.get("last"))
    price = last if last is not None else (((bid or 0.0) + (ask or 0.0)) / 2.0 if bid and ask else None)
    spread_bps = ((ask - bid) / bid) * 10_000.0 if bid and ask and bid > 0 else None

    base_volume = _float(ticker.get("baseVolume")) or 0.0
    quote_volume_24h = _float(ticker.get("quoteVolume"))
    if quote_volume_24h is None and price is not None:
        quote_volume_24h = base_volume * price

    has_price = price is not None and price > 0.0
    has_book = bid is not None and ask is not None and spread_bps is not None
    data_quality = 1.0 if (has_price and has_book) else (0.5 if has_price else 0.0)

    funding_rate = _float(funding.get("fundingRate")) if isinstance(funding, dict) else None
    mark_price = _float(funding.get("markPrice")) if isinstance(funding, dict) else None
    index_price = _float(funding.get("indexPrice")) if isinstance(funding, dict) else None

    return {
        "canonical_symbol": canonical_symbol,
        "exchange_symbol": perp_symbol,
        "price": price,
        "bid": bid,
        "ask": ask,
        "spread_bps": spread_bps,
        "quote_volume_24h": quote_volume_24h,
        "data_quality": data_quality,
        "funding_rate": funding_rate,
        "funding_rate_source": "kraken_futures_live" if funding_rate is not None else "unavailable",
        "mark_price": mark_price,
        "index_price": index_price,
    }


def run_derivatives_observer_once(
    client: Any,
    conn: Any,
    cfg: Any,
    *,
    venue: str = "kraken_futures",
    symbols: tuple[str, ...] | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    """Collect one public-data cycle for the configured perpetual symbols.

    Persists one ``observation_snapshots`` row per symbol tagged with
    ``venue`` (default ``kraken_futures``) so ``derivatives_trend_lab.py``
    can prefer this genuine live feed over the spot proxy once rows exist.
    """
    ensure_schema(conn)
    symbol_map = perpetual_symbol_map(cfg)
    canonical_symbols = tuple(
        symbols
        if symbols is not None
        else (getattr(cfg, "derivatives_trend_symbols", list(symbol_map.keys())) or list(symbol_map.keys()))
    )
    observed_at = float(now_ts if now_ts is not None else time.time())
    run_id = f"deriv-obs-{int(observed_at * 1000)}-{uuid.uuid4().hex[:8]}"

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for canonical_symbol in canonical_symbols:
        perp_symbol = symbol_map.get(canonical_symbol)
        if not perp_symbol:
            errors.append(f"{canonical_symbol}: no perpetual symbol mapping configured")
            continue
        try:
            snapshot = _snapshot_for_symbol(client, canonical_symbol, perp_symbol)
        except Exception as exc:  # public-endpoint network/venue failure, not fatal to the cycle
            errors.append(f"{canonical_symbol}: {type(exc).__name__}: {exc}")
            continue

        payload = {
            "schema": "hivenance_derivatives_observation_snapshot_v1",
            "authority": "context_only",
            "execution_authority": "none",
            "product": "perpetual_future",
            "canonical_symbol": canonical_symbol,
            "exchange_symbol": perp_symbol,
            "bid": snapshot["bid"],
            "ask": snapshot["ask"],
            "funding_rate": snapshot["funding_rate"],
            "funding_rate_source": snapshot["funding_rate_source"],
            "mark_price": snapshot["mark_price"],
            "index_price": snapshot["index_price"],
        }
        conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
             data_quality, observation_eligible, execution_eligible, payload)
            VALUES (?,?,?,?,?,?,?,?,?,0,?)
            """,
            (
                run_id,
                observed_at,
                str(venue),
                canonical_symbol,
                snapshot["price"],
                snapshot["quote_volume_24h"],
                snapshot["spread_bps"],
                snapshot["data_quality"],
                1 if snapshot["data_quality"] >= 0.99 else 0,
                json.dumps(payload, sort_keys=True, default=str),
            ),
        )
        results.append(
            {
                "symbol": canonical_symbol,
                "exchange_symbol": perp_symbol,
                "price": snapshot["price"],
                "spread_bps": snapshot["spread_bps"],
                "data_quality": snapshot["data_quality"],
                "funding_rate": snapshot["funding_rate"],
            }
        )
    conn.commit()

    return {
        "schema": "hivenance_derivatives_observer_run_v1",
        "run_id": run_id,
        "venue": str(venue),
        "authority": "context_only",
        "execution_authority": "none",
        "execution_wired": False,
        "orders_submitted": 0,
        "observed_ts": observed_at,
        "symbols_attempted": len(canonical_symbols),
        "symbols_successful": len(results),
        "results": results,
        "errors": errors,
    }
