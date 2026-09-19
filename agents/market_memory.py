from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

AUTHORITY = "PUBLIC_MARKET_RESEARCH_MEMORY_ONLY_NO_EXECUTION_AUTHORITY"
SCHEMA = "hivenance_market_memory_v1"

def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()

class MarketMemory:
    """Canonical append-only memory spine for HiveNance research.

    One line of memory means one immutable, timestamped fact/event. All organs may
    read this spine. Writers cannot grant execution or promotion authority.
    """

    def __init__(self, path: str | Path = "data/hivenance_market_memory.db") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._schema()

    def _schema(self) -> None:
        self.conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS memory_line(
          line_id TEXT PRIMARY KEY,
          observed_ts_ms INTEGER NOT NULL,
          effective_ts_ms INTEGER NOT NULL,
          source TEXT NOT NULL,
          kind TEXT NOT NULL,
          symbol TEXT,
          world_state_id TEXT,
          payload_json TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL,
          authority TEXT NOT NULL,
          execution_eligible INTEGER NOT NULL DEFAULT 0,
          promotion_eligible INTEGER NOT NULL DEFAULT 0,
          inserted_ts_ms INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memory_line_time
          ON memory_line(effective_ts_ms);
        CREATE INDEX IF NOT EXISTS idx_memory_line_symbol_time
          ON memory_line(symbol,effective_ts_ms);
        CREATE INDEX IF NOT EXISTS idx_memory_line_kind_time
          ON memory_line(kind,effective_ts_ms);

        CREATE TABLE IF NOT EXISTS market_bar(
          symbol TEXT NOT NULL,
          timeframe TEXT NOT NULL,
          open_ts_ms INTEGER NOT NULL,
          open REAL, high REAL, low REAL, close REAL, volume REAL,
          source TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL,
          PRIMARY KEY(symbol,timeframe,open_ts_ms,source)
        );
        CREATE INDEX IF NOT EXISTS idx_market_bar_lookup
          ON market_bar(symbol,timeframe,open_ts_ms);
        """)
        self.conn.commit()

    def append(
        self, *, source: str, kind: str, payload: dict[str, Any],
        effective_ts_ms: int, observed_ts_ms: int | None = None,
        symbol: str | None = None, world_state_id: str | None = None,
    ) -> str:
        observed = int(observed_ts_ms or time.time() * 1000)
        body = {
            "schema": SCHEMA, "source": str(source), "kind": str(kind),
            "symbol": symbol, "effective_ts_ms": int(effective_ts_ms),
            "world_state_id": world_state_id, "payload": payload,
        }
        payload_hash = _digest(payload)
        line_id = _digest(body)
        self.conn.execute(
            """INSERT OR IGNORE INTO memory_line VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (line_id, observed, int(effective_ts_ms), str(source), str(kind),
             symbol, world_state_id, _json(payload), payload_hash, AUTHORITY,
             0, 0, int(time.time()*1000)),
        )
        self.conn.commit()
        return line_id

    def append_bar(
        self, *, symbol: str, timeframe: str, row: Iterable[float],
        source: str = "kraken_public_ohlcv",
    ) -> str:
        values=list(row)
        if len(values) < 6:
            raise ValueError("OHLCV row requires timestamp, open, high, low, close, volume")
        ts=int(values[0])
        payload={"timeframe":timeframe,"open":float(values[1]),"high":float(values[2]),
                 "low":float(values[3]),"close":float(values[4]),"volume":float(values[5])}
        ph=_digest(payload)
        self.conn.execute(
            """INSERT OR IGNORE INTO market_bar VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (symbol,timeframe,ts,payload["open"],payload["high"],payload["low"],
             payload["close"],payload["volume"],source,ph),
        )
        line=self.append(source=source,kind="MARKET_BAR",payload=payload,
                         effective_ts_ms=ts,symbol=symbol)
        return line

    def bars(self, symbol: str, timeframe: str, *, since_ms: int | None = None,
             limit: int | None = None) -> list[dict[str, Any]]:
        sql="SELECT * FROM market_bar WHERE symbol=? AND timeframe=?"
        args:[Any]=[symbol,timeframe]
        if since_ms is not None:
            sql+=" AND open_ts_ms>=?"; args.append(int(since_ms))
        sql+=" ORDER BY open_ts_ms ASC"
        if limit is not None:
            sql+=" LIMIT ?"; args.append(max(1,int(limit)))
        return [dict(r) for r in self.conn.execute(sql,args).fetchall()]

    def lines(self, *, symbol: str | None = None, kind: str | None = None,
              since_ms: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        clauses=[]; args=[]
        if symbol is not None: clauses.append("symbol=?"); args.append(symbol)
        if kind is not None: clauses.append("kind=?"); args.append(kind)
        if since_ms is not None: clauses.append("effective_ts_ms>=?"); args.append(int(since_ms))
        sql="SELECT * FROM memory_line"
        if clauses: sql+=" WHERE "+" AND ".join(clauses)
        sql+=" ORDER BY effective_ts_ms ASC LIMIT ?"; args.append(max(1,int(limit)))
        out=[]
        for row in self.conn.execute(sql,args):
            d=dict(row); d["payload"]=json.loads(d.pop("payload_json")); out.append(d)
        return out

    def close(self) -> None:
        self.conn.close()
