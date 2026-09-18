from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from strategies.volatility_breakout.derivatives_observer import (
    DEFAULT_PERPETUAL_SYMBOL_MAP,
    perpetual_symbol_map,
    run_derivatives_observer_once,
)
from strategies.volatility_breakout.derivatives_trend_lab import (
    run_derivatives_trend_lab,
)


class _FakeKrakenFuturesClient:
    """Deterministic stand-in for ccxt.krakenfutures -- no network calls."""

    def __init__(self, *, tickers=None, books=None, funding=None, fail_symbols=None):
        self._tickers = tickers or {}
        self._books = books or {}
        self._funding = funding or {}
        self._fail_symbols = fail_symbols or set()

    def fetch_ticker(self, symbol):
        if symbol in self._fail_symbols:
            raise RuntimeError("simulated network failure")
        return self._tickers[symbol]

    def fetch_order_book(self, symbol, limit=10):
        return self._books[symbol]

    def fetch_funding_rate(self, symbol):
        return self._funding.get(symbol, {})


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE observation_snapshots (
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


def _cfg(**overrides) -> SimpleNamespace:
    base = dict(derivatives_trend_symbols=["BTC/USD", "ETH/USD"])
    base.update(overrides)
    return SimpleNamespace(**base)


def test_perpetual_symbol_map_defaults() -> None:
    cfg = _cfg()
    assert perpetual_symbol_map(cfg) == DEFAULT_PERPETUAL_SYMBOL_MAP


def test_perpetual_symbol_map_honors_override() -> None:
    cfg = _cfg(derivatives_trend_perpetual_symbol_map={"BTC/USD": "BTC/USD:USD-CUSTOM"})
    assert perpetual_symbol_map(cfg)["BTC/USD"] == "BTC/USD:USD-CUSTOM"


def test_run_derivatives_observer_once_persists_live_snapshot() -> None:
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    cfg = _cfg(derivatives_trend_symbols=["BTC/USD"])
    client = _FakeKrakenFuturesClient(
        tickers={"BTC/USD:USD": {"last": 64000.0, "baseVolume": 100.0, "quoteVolume": None}},
        books={"BTC/USD:USD": {"bids": [[63990.0, 1.0]], "asks": [[64010.0, 1.0]]}},
        funding={"BTC/USD:USD": {"fundingRate": -0.0001, "markPrice": 64001.0, "indexPrice": 63999.0}},
    )

    payload = run_derivatives_observer_once(client, conn, cfg, now_ts=1_000_000.0)

    assert payload["symbols_successful"] == 1
    assert payload["symbols_attempted"] == 1
    assert payload["errors"] == []
    assert payload["execution_authority"] == "none"
    assert payload["execution_wired"] is False
    assert payload["orders_submitted"] == 0

    row = conn.execute(
        "SELECT venue, symbol, price, spread_bps, data_quality, payload FROM observation_snapshots"
    ).fetchone()
    assert row is not None
    venue, symbol, price, spread_bps, data_quality, payload_json = row
    assert venue == "kraken_futures"
    assert symbol == "BTC/USD"
    assert price == 64000.0
    assert spread_bps > 0.0
    assert data_quality == 1.0
    stored = json.loads(payload_json)
    assert stored["exchange_symbol"] == "BTC/USD:USD"
    assert stored["funding_rate"] == -0.0001
    assert stored["funding_rate_source"] == "kraken_futures_live"
    assert stored["authority"] == "context_only"
    assert stored["execution_authority"] == "none"


def test_run_derivatives_observer_once_records_errors_without_raising() -> None:
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    cfg = _cfg(derivatives_trend_symbols=["BTC/USD", "ETH/USD"])
    client = _FakeKrakenFuturesClient(
        tickers={"ETH/USD:USD": {"last": 3000.0, "baseVolume": 10.0, "quoteVolume": None}},
        books={"ETH/USD:USD": {"bids": [[2999.0, 1.0]], "asks": [[3001.0, 1.0]]}},
        fail_symbols={"BTC/USD:USD"},
    )

    payload = run_derivatives_observer_once(client, conn, cfg, now_ts=1_000_000.0)

    assert payload["symbols_attempted"] == 2
    assert payload["symbols_successful"] == 1
    assert len(payload["errors"]) == 1
    assert "BTC/USD" in payload["errors"][0]


def test_derivatives_trend_lab_prefers_live_futures_rows_over_spot_proxy() -> None:
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    cfg = SimpleNamespace(
        phase3_venue_economics_receipt="",
        derivatives_trend_symbols=["BTC/USD"],
        derivatives_trend_horizons_seconds=[86400],
        derivatives_trend_lookbacks_seconds=[3600],
        derivatives_trend_min_history_points=2,
        derivatives_trend_min_data_quality=0.99,
        derivatives_trend_max_spread_bps=40.0,
        derivatives_trend_min_momentum_bps=20.0,
        derivatives_trend_breakout_lookback_multiplier=1.0,
        derivatives_trend_min_vol_expansion_ratio=0.0,
        derivatives_trend_vol_baseline_multiplier=4.0,
        derivatives_trend_min_market_breadth=0.50,
        derivatives_trend_slippage_bps=2.0,
        derivatives_trend_cost_stress_multiplier=1.5,
        derivatives_trend_min_entries_per_slice=2,
        derivatives_trend_min_lower_bound_net_bps=5.0,
        derivatives_trend_post_only_fill_probability=0.75,
        derivatives_trend_funding_drag_bps_per_8h=1.0,
        derivatives_trend_max_concurrent_positions=1,
        derivatives_trend_maker_fee_bps=2.0,
        derivatives_trend_taker_fee_bps=5.0,
        derivatives_trend_allow_unverified_fees=True,
        derivatives_trend_phase2_model_enabled=True,
        derivatives_trend_ml_veto_enabled=True,
        derivatives_trend_ml_veto_max_failure_probability=0.50,
    )

    # Spot proxy rows: flat series (would yield no accepted UP momentum).
    for idx in range(40):
        conn.execute(
            "INSERT INTO observation_snapshots (run_id, ts, venue, symbol, price, spread_bps, data_quality, payload) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("spot-run", idx * 3600.0, "kraken", "BTC/USD", 100.0, 4.0, 1.0, json.dumps({})),
        )
    # Live futures rows: monotonic uptrend -- should be preferred and drive acceptance.
    for idx in range(40):
        price = 100.0 + idx * 3.0
        conn.execute(
            "INSERT INTO observation_snapshots (run_id, ts, venue, symbol, price, spread_bps, data_quality, payload) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("futures-run", idx * 3600.0, "kraken_futures", "BTC/USD", price, 4.0, 1.0, json.dumps({})),
        )
    conn.commit()

    summary = run_derivatives_trend_lab(conn, cfg, venue="kraken_futures", now_ts=1_800_000_000.0)

    assert summary["price_data_source_by_symbol"]["BTC/USD"] == "kraken_futures_live_perpetual_feed"
    assert summary["price_data_source"] == "kraken_futures_live_perpetual_feed"
    up_receipts = [
        row
        for row in summary["best_slices"]
        if row["symbol"] == "BTC/USD" and row["direction"] == "UP"
    ]
    assert any(row["entries"] > 0 for row in up_receipts)
