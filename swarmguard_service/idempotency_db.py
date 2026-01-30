from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional


class IdempotencyDB:
    def __init__(self, path: str = "swarmguard.db") -> None:
        self.path = path
        self._init()

    def _init(self) -> None:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency (
                request_id TEXT PRIMARY KEY,
                response_json TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        con.commit()
        con.close()

    def get(self, request_id: str) -> Optional[Dict[str, Any]]:
        con = sqlite3.connect(self.path)
        cur = con.cursor()
        cur.execute("SELECT response_json FROM idempotency WHERE request_id=?", (request_id,))
        row = cur.fetchone()
        con.close()
        if not row:
            return None
        return json.loads(row[0])

    def put_atomic(self, request_id: str, response: Dict[str, Any], created_at: int) -> None:
        con = sqlite3.connect(self.path)
        try:
            cur = con.cursor()
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                "INSERT INTO idempotency(request_id, response_json, created_at) VALUES (?,?,?)",
                (request_id, json.dumps(response), created_at),
            )
            con.commit()
        except sqlite3.IntegrityError:
            con.rollback()
            raise
        finally:
            con.close()
