from __future__ import annotations
import sqlite3
from typing import Optional, Dict, Any, List
import json
import time

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS accounts (
  account TEXT PRIMARY KEY,
  available INTEGER NOT NULL DEFAULT 0,
  locked INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
  request_id TEXT PRIMARY KEY,
  response_json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account TEXT NOT NULL,
  entry_type TEXT NOT NULL,
  amount INTEGER NOT NULL,
  balance_available INTEGER NOT NULL,
  balance_locked INTEGER NOT NULL,
  ref TEXT,
  request_id TEXT NOT NULL,
  ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ledger_account_ts ON ledger(account, ts);
"""


class BuzzDB:
    def __init__(self, path: str = "buzzservice.db"):
        self.path = path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        con = self._connect()
        try:
            con.executescript(SCHEMA)
        finally:
            con.close()

    # -------- idempotency --------
    def idem_get(self, request_id: str) -> Optional[Dict[str, Any]]:
        con = self._connect()
        try:
            row = con.execute("SELECT response_json FROM idempotency WHERE request_id=?", (request_id,)).fetchone()
            return json.loads(row["response_json"]) if row else None
        finally:
            con.close()

    def idem_put_atomic(self, request_id: str, response: Dict[str, Any], created_at: int) -> None:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "INSERT INTO idempotency(request_id, response_json, created_at) VALUES (?,?,?)",
                (request_id, json.dumps(response), created_at)
            )
            con.execute("COMMIT")
        except sqlite3.IntegrityError:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    # -------- accounts --------
    def _ensure_account_row(self, con: sqlite3.Connection, account: str) -> None:
        now = int(time.time())
        con.execute(
            "INSERT OR IGNORE INTO accounts(account, available, locked, updated_at) VALUES (?,?,?,?)",
            (account, 0, 0, now)
        )

    def get_account(self, account: str) -> Dict[str, Any]:
        con = self._connect()
        try:
            self._ensure_account_row(con, account)
            row = con.execute("SELECT account, available, locked, updated_at FROM accounts WHERE account=?", (account,)).fetchone()
            return dict(row)
        finally:
            con.close()

    def get_ledger(self, account: str, limit: int = 100) -> List[Dict[str, Any]]:
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT id, account, entry_type, amount, balance_available, balance_locked, ref, request_id, ts "
                "FROM ledger WHERE account=? ORDER BY ts DESC, id DESC LIMIT ?",
                (account, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    # -------- atomic ledger operations --------
    def credit(self, account: str, amount: int, request_id: str, ref: str = "") -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("amount must be > 0")

        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            self._ensure_account_row(con, account)

            row = con.execute("SELECT available, locked FROM accounts WHERE account=?", (account,)).fetchone()
            available, locked = int(row["available"]), int(row["locked"])
            available += amount

            now = int(time.time())
            con.execute("UPDATE accounts SET available=?, updated_at=? WHERE account=?", (available, now, account))

            con.execute(
                "INSERT INTO ledger(account, entry_type, amount, balance_available, balance_locked, ref, request_id, ts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (account, "CREDIT", amount, available, locked, ref, request_id, now)
            )
            con.execute("COMMIT")
            return {"account": account, "available": available, "locked": locked}
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def lock(self, account: str, amount: int, request_id: str, ref: str = "") -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("amount must be > 0")

        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            self._ensure_account_row(con, account)

            row = con.execute("SELECT available, locked FROM accounts WHERE account=?", (account,)).fetchone()
            available, locked = int(row["available"]), int(row["locked"])

            if available < amount:
                raise ValueError("insufficient available balance")

            available -= amount
            locked += amount
            now = int(time.time())
            con.execute("UPDATE accounts SET available=?, locked=?, updated_at=? WHERE account=?", (available, locked, now, account))

            con.execute(
                "INSERT INTO ledger(account, entry_type, amount, balance_available, balance_locked, ref, request_id, ts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (account, "LOCK", amount, available, locked, ref, request_id, now)
            )

            con.execute("COMMIT")
            return {"account": account, "available": available, "locked": locked}
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def release(self, account: str, amount: int, request_id: str, ref: str = "") -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("amount must be > 0")

        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            self._ensure_account_row(con, account)

            row = con.execute("SELECT available, locked FROM accounts WHERE account=?", (account,)).fetchone()
            available, locked = int(row["available"]), int(row["locked"])

            if locked < amount:
                raise ValueError("insufficient locked balance")

            locked -= amount
            available += amount
            now = int(time.time())
            con.execute("UPDATE accounts SET available=?, locked=?, updated_at=? WHERE account=?", (available, locked, now, account))

            con.execute(
                "INSERT INTO ledger(account, entry_type, amount, balance_available, balance_locked, ref, request_id, ts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (account, "RELEASE", amount, available, locked, ref, request_id, now)
            )
            con.execute("COMMIT")
            return {"account": account, "available": available, "locked": locked}
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def slash(self, account: str, amount: int, request_id: str, ref: str = "") -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("amount must be > 0")

        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            self._ensure_account_row(con, account)

            row = con.execute("SELECT available, locked FROM accounts WHERE account=?", (account,)).fetchone()
            available, locked = int(row["available"]), int(row["locked"])

            if locked < amount:
                raise ValueError("insufficient locked balance for slash")

            locked -= amount
            now = int(time.time())
            con.execute("UPDATE accounts SET locked=?, updated_at=? WHERE account=?", (locked, now, account))

            con.execute(
                "INSERT INTO ledger(account, entry_type, amount, balance_available, balance_locked, ref, request_id, ts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (account, "SLASH", amount, available, locked, ref, request_id, now)
            )
            con.execute("COMMIT")
            return {"account": account, "available": available, "locked": locked}
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()
