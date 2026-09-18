#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from typing import Any

from strategies.relative_value_lab.microstructure import SequentialMicrostructureEngine


AUTHORITY = "PUBLIC_MARKET_RESEARCH_CONTEXT_ONLY_NO_EXECUTION_AUTHORITY"
KRAKEN_PUBLIC_BASE = "https://api.kraken.com/0/public"
DEFAULT_SYMBOLS = (
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "XRP/USD",
    "ADA/USD",
    "AVAX/USD",
    "DOGE/USD",
    "HYPE/USD",
)


def _canonical_wsname(wsname: str) -> str:
    return str(wsname or "").upper().replace("XBT/", "BTC/").replace("XDG/", "DOGE/")


class KrakenPublicMicrostructureFeed:
    def __init__(self, symbols: list[str], *, timeout_sec: float = 8.0) -> None:
        self.requested_symbols = list(symbols)
        self.timeout_sec = float(timeout_sec)
        self.api_pairs: dict[str, str] = {}
        self.result_key_to_symbol: dict[str, str] = {}
        self.trade_since: dict[str, str] = {}
        self._load_pair_map()

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{KRAKEN_PUBLIC_BASE}/{endpoint}"
        if query:
            url += "?" + query
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Hivenance-Phoenix-Relative-Value-Research/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        errors = payload.get("error") or []
        if errors:
            raise RuntimeError(f"{endpoint}: {';'.join(str(item) for item in errors)}")
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    def _load_pair_map(self) -> None:
        pairs = self._get("AssetPairs", {})
        wanted = set(self.requested_symbols)
        for result_key, info in pairs.items():
            if not isinstance(info, dict):
                continue
            wsname = _canonical_wsname(info.get("wsname"))
            if wsname not in wanted:
                continue
            self.api_pairs[wsname] = str(info.get("altname") or result_key)
            self.result_key_to_symbol[str(result_key)] = wsname
        if not self.api_pairs:
            raise RuntimeError("No requested Kraken public pairs resolved")

    @property
    def symbols(self) -> list[str]:
        return sorted(self.api_pairs)

    @property
    def missing_symbols(self) -> list[str]:
        return sorted(set(self.requested_symbols) - set(self.api_pairs))

    def depth(self, symbol: str, *, count: int = 50) -> dict[str, Any]:
        result = self._get("Depth", {"pair": self.api_pairs[symbol], "count": int(count)})
        for key, row in result.items():
            if key == "last" or not isinstance(row, dict):
                continue
            return {
                "bids": row.get("bids") or [],
                "asks": row.get("asks") or [],
            }
        return {"bids": [], "asks": []}

    def trades(self, symbol: str) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pair": self.api_pairs[symbol]}
        since = self.trade_since.get(symbol)
        if since:
            params["since"] = since
        result = self._get("Trades", params)
        if result.get("last") is not None:
            self.trade_since[symbol] = str(result["last"])

        rows: list[Any] = []
        for key, value in result.items():
            if key == "last":
                continue
            if isinstance(value, list):
                rows = value
                break

        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 4:
                continue
            side_raw = str(row[3] or "").lower()
            side = "buy" if side_raw == "b" else "sell" if side_raw == "s" else ""
            out.append({
                "price": row[0],
                "amount": row[1],
                "timestamp": row[2],
                "side": side,
                "source_side": side_raw,
            })
        return out


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS relative_value_microstructure_runs (
    run_id TEXT PRIMARY KEY,
    started_ts REAL NOT NULL,
    completed_ts REAL,
    status TEXT NOT NULL,
    authority TEXT NOT NULL,
    requested_symbols_json TEXT NOT NULL,
    active_symbols_json TEXT NOT NULL,
    missing_symbols_json TEXT NOT NULL,
    interval_sec REAL NOT NULL,
    depth_count INTEGER NOT NULL,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS relative_value_microstructure_snapshots (
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    best_bid REAL,
    best_ask REAL,
    mid REAL,
    spread_bps REAL,
    book_imbalance_25bps REAL,
    quote_ofi_proxy REAL,
    aggressor_flow_imbalance REAL,
    trade_count INTEGER NOT NULL,
    trade_intensity_per_sec REAL,
    depth_recovery_score REAL,
    data_quality REAL NOT NULL,
    PRIMARY KEY (run_id, symbol, timestamp_ms)
);

CREATE INDEX IF NOT EXISTS idx_rv_micro_symbol_ts
ON relative_value_microstructure_snapshots(symbol, timestamp_ms);
"""


def init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def insert_snapshot(conn: sqlite3.Connection, run_id: str, snapshot: Any) -> None:
    payload = snapshot.to_dict()
    conn.execute(
        """
        INSERT OR REPLACE INTO relative_value_microstructure_snapshots (
            run_id, symbol, timestamp_ms, snapshot_json,
            best_bid, best_ask, mid, spread_bps,
            book_imbalance_25bps, quote_ofi_proxy,
            aggressor_flow_imbalance, trade_count,
            trade_intensity_per_sec, depth_recovery_score, data_quality
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            snapshot.symbol,
            snapshot.timestamp_ms,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            snapshot.best_bid,
            snapshot.best_ask,
            snapshot.mid,
            snapshot.spread_bps,
            snapshot.book_imbalance_25bps,
            snapshot.quote_ofi_proxy,
            snapshot.aggressor_flow_imbalance,
            snapshot.trade_count,
            snapshot.trade_intensity_per_sec,
            snapshot.depth_recovery_score,
            snapshot.data_quality,
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phoenix public microstructure observer")
    parser.add_argument("--database", type=Path, default=Path("data/relative_value_microstructure.db"))
    parser.add_argument("--duration-sec", type=int, default=900)
    parser.add_argument("--interval-sec", type=float, default=15.0)
    parser.add_argument("--depth-count", type=int, default=50)
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    interval = max(5.0, float(args.interval_sec))
    feed = KrakenPublicMicrostructureFeed(args.symbols, timeout_sec=args.timeout_sec)
    engine = SequentialMicrostructureEngine()
    conn = init_db(args.database)
    run_id = "rv-micro-" + uuid.uuid4().hex[:12]
    started = time.time()

    conn.execute(
        """
        INSERT INTO relative_value_microstructure_runs (
            run_id, started_ts, completed_ts, status, authority,
            requested_symbols_json, active_symbols_json, missing_symbols_json,
            interval_sec, depth_count, error_count
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            run_id,
            started,
            "RUNNING",
            AUTHORITY,
            json.dumps(args.symbols),
            json.dumps(feed.symbols),
            json.dumps(feed.missing_symbols),
            interval,
            int(args.depth_count),
        ),
    )
    conn.commit()

    print(f"Phoenix Relative-Value Microstructure // {run_id}")
    print(f"authority={AUTHORITY}")
    print(f"active={','.join(feed.symbols)}")
    if feed.missing_symbols:
        print(f"missing={','.join(feed.missing_symbols)}")
    print("PRIVATE ORDERS: 0")

    errors = 0
    status = "COMPLETE"
    try:
        while True:
            cycle_started = time.time()
            if int(args.duration_sec) > 0 and cycle_started - started >= int(args.duration_sec):
                break
            timestamp_ms = int(cycle_started * 1000)
            observed = 0
            for symbol in feed.symbols:
                try:
                    book = feed.depth(symbol, count=args.depth_count)
                    trades = feed.trades(symbol)
                    snap = engine.build(
                        symbol=symbol,
                        timestamp_ms=timestamp_ms,
                        orderbook=book,
                        trades=trades,
                        observation_window_sec=interval,
                    )
                    insert_snapshot(conn, run_id, snap)
                    observed += 1
                except Exception as exc:
                    errors += 1
                    print(f"WARN {symbol}: {type(exc).__name__}: {exc}")
            conn.commit()
            print(f"cycle ts={timestamp_ms} observed={observed}/{len(feed.symbols)} errors={errors}")
            elapsed = time.time() - cycle_started
            time.sleep(max(0.0, interval - elapsed))
    except KeyboardInterrupt:
        status = "INTERRUPTED"
    finally:
        completed = time.time()
        conn.execute(
            """
            UPDATE relative_value_microstructure_runs
            SET completed_ts=?, status=?, error_count=?
            WHERE run_id=?
            """,
            (completed, status, errors, run_id),
        )
        conn.commit()
        conn.close()

    print(f"status={status} errors={errors}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())