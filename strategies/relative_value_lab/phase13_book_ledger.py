from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .phase13_book_router import Phase13ForecastBookRow


def _json(x:Any)->str:
    return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)


def _sha(x:Any)->str:
    return "sha256:"+hashlib.sha256(_json(x).encode("utf-8")).hexdigest()


class Phase13BookLedger:
    """Durable research-only custody for Phase-13 forecast books and settlements."""

    def __init__(self,path:str|Path="data/hivenance_phase13_books.db")->None:
        self.path=str(path)
        self.conn=sqlite3.connect(self.path)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS phase13_forecast_book(
            row_id TEXT PRIMARY KEY,
            freeze_id TEXT NOT NULL,
            book_id TEXT NOT NULL,
            world_state_id TEXT NOT NULL,
            world_state_hash TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            horizon_seconds INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            inserted_ts_ms INTEGER NOT NULL,
            execution_eligible INTEGER NOT NULL DEFAULT 0,
            promotion_eligible INTEGER NOT NULL DEFAULT 0,
            UNIQUE(freeze_id,book_id,world_state_id,symbol,timestamp_ms,horizon_seconds,model_id)
        )
        """)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS phase13_settlement_book(
            settlement_id TEXT PRIMARY KEY,
            forecast_row_id TEXT NOT NULL,
            freeze_id TEXT NOT NULL,
            book_id TEXT NOT NULL,
            world_state_id TEXT NOT NULL,
            world_state_hash TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timestamp_ms INTEGER NOT NULL,
            horizon_seconds INTEGER NOT NULL,
            model_id TEXT NOT NULL,
            settled_ts REAL NOT NULL,
            realized_net_bps REAL,
            realized_cost_bps REAL,
            fill_status TEXT,
            filled INTEGER,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            inserted_ts_ms INTEGER NOT NULL,
            execution_eligible INTEGER NOT NULL DEFAULT 0,
            promotion_eligible INTEGER NOT NULL DEFAULT 0,
            UNIQUE(forecast_row_id)
        )
        """)
        self.conn.commit()

    @staticmethod
    def row_id(row:Phase13ForecastBookRow)->str:
        return _sha({
            "freeze_id":row.freeze_id,
            "book_id":row.book_id,
            "world_state_id":row.world_state_id,
            "world_state_hash":row.world_state_hash,
            "symbol":row.symbol,
            "timestamp_ms":row.timestamp_ms,
            "horizon_seconds":row.horizon_seconds,
            "model_id":row.model_id,
        })

    def persist_forecasts(self,rows:Iterable[Phase13ForecastBookRow])->int:
        inserted=0
        for row in rows:
            if row.execution_eligible or row.promotion_eligible:
                raise ValueError("phase13_forecast_authority_escalation_forbidden")
            payload=row.to_dict()
            rid=self.row_id(row)
            before=self.conn.total_changes
            self.conn.execute(
                """INSERT OR IGNORE INTO phase13_forecast_book
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rid,row.freeze_id,row.book_id,row.world_state_id,row.world_state_hash,
                    row.symbol,int(row.timestamp_ms),int(row.horizon_seconds),row.model_id,
                    _json(payload),_sha(payload),int(time.time()*1000),0,0,
                ),
            )
            inserted += 1 if self.conn.total_changes>before else 0
        self.conn.commit()
        return inserted

    def pending_forecasts(
        self,
        *,
        freeze_id:str,
        target_time_ms:int|None=None,
        limit:int=10000,
    )->list[dict[str,Any]]:
        params:list[Any]=[str(freeze_id)]
        where="f.freeze_id=? AND s.forecast_row_id IS NULL"
        if target_time_ms is not None:
            where+=" AND (f.timestamp_ms + f.horizon_seconds*1000) <= ?"
            params.append(int(target_time_ms))
        params.append(int(limit))
        rows=self.conn.execute(
            f"""SELECT f.* FROM phase13_forecast_book f
            LEFT JOIN phase13_settlement_book s ON s.forecast_row_id=f.row_id
            WHERE {where}
            ORDER BY f.timestamp_ms,f.book_id,f.model_id,f.horizon_seconds
            LIMIT ?""",
            tuple(params),
        ).fetchall()
        out=[]
        for row in rows:
            d=dict(row)
            d["payload"]=json.loads(d.pop("payload_json"))
            out.append(d)
        return out

    def persist_settlement(
        self,
        *,
        forecast_row_id:str,
        freeze_id:str,
        book_id:str,
        world_state_id:str,
        world_state_hash:str,
        symbol:str,
        timestamp_ms:int,
        horizon_seconds:int,
        model_id:str,
        settled_ts:float,
        realized_net_bps:float|None,
        realized_cost_bps:float|None,
        fill_status:str,
        filled:bool,
        payload:Mapping[str,Any],
    )->str:
        if not str(world_state_hash).startswith("sha256:"):
            raise ValueError("phase13_settlement_world_hash_required")
        body={
            "forecast_row_id":str(forecast_row_id),
            "freeze_id":str(freeze_id),
            "book_id":str(book_id),
            "world_state_id":str(world_state_id),
            "world_state_hash":str(world_state_hash),
            "symbol":str(symbol),
            "timestamp_ms":int(timestamp_ms),
            "horizon_seconds":int(horizon_seconds),
            "model_id":str(model_id),
            "settled_ts":float(settled_ts),
            "realized_net_bps":realized_net_bps,
            "realized_cost_bps":realized_cost_bps,
            "fill_status":str(fill_status),
            "filled":bool(filled),
            "payload":dict(payload),
            "execution_eligible":False,
            "promotion_eligible":False,
        }
        sid=_sha(body)
        self.conn.execute(
            """INSERT OR IGNORE INTO phase13_settlement_book
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid,str(forecast_row_id),str(freeze_id),str(book_id),
                str(world_state_id),str(world_state_hash),str(symbol),
                int(timestamp_ms),int(horizon_seconds),str(model_id),
                float(settled_ts),
                None if realized_net_bps is None else float(realized_net_bps),
                None if realized_cost_bps is None else float(realized_cost_bps),
                str(fill_status),1 if filled else 0,
                _json(body),_sha(body),int(time.time()*1000),0,0,
            ),
        )
        self.conn.commit()
        return sid

    def counts(self,*,freeze_id:str)->dict[str,int]:
        forecasts=int(self.conn.execute(
            "SELECT COUNT(*) FROM phase13_forecast_book WHERE freeze_id=?",
            (str(freeze_id),),
        ).fetchone()[0])
        settlements=int(self.conn.execute(
            "SELECT COUNT(*) FROM phase13_settlement_book WHERE freeze_id=?",
            (str(freeze_id),),
        ).fetchone()[0])
        books=int(self.conn.execute(
            "SELECT COUNT(DISTINCT book_id) FROM phase13_forecast_book WHERE freeze_id=?",
            (str(freeze_id),),
        ).fetchone()[0])
        worlds=int(self.conn.execute(
            "SELECT COUNT(DISTINCT world_state_id) FROM phase13_forecast_book WHERE freeze_id=?",
            (str(freeze_id),),
        ).fetchone()[0])
        return {
            "forecasts":forecasts,
            "settlements":settlements,
            "books":books,
            "worlds":worlds,
        }

    def export_settlements(self,*,freeze_id:str)->dict[str,Any]:
        rows=[]
        for row in self.conn.execute(
            """SELECT * FROM phase13_settlement_book
            WHERE freeze_id=? ORDER BY timestamp_ms,book_id,model_id,horizon_seconds""",
            (str(freeze_id),),
        ):
            d=dict(row)
            payload=json.loads(d.pop("payload_json"))
            rows.append({
                "settlement_id":d["settlement_id"],
                "freeze_id":d["freeze_id"],
                "book_id":d["book_id"],
                "world_state_id":d["world_state_id"],
                "world_state_hash":d["world_state_hash"],
                "symbol":d["symbol"],
                "timestamp_ms":d["timestamp_ms"],
                "horizon_seconds":d["horizon_seconds"],
                "model_id":d["model_id"],
                "settled_ts":d["settled_ts"],
                "realized_net_bps":d["realized_net_bps"],
                "realized_cost_bps":d["realized_cost_bps"],
                "fill_status":d["fill_status"],
                "filled":bool(d["filled"]),
                **{
                    k:v for k,v in dict(payload.get("payload") or {}).items()
                    if k not in {
                        "freeze_id","book_id","world_state_id","world_state_hash",
                        "symbol","timestamp_ms","horizon_seconds","model_id"
                    }
                },
            })
        return {
            "schema":"hivenance_phase13_settlement_book_v1",
            "freeze_id":str(freeze_id),
            "rows":rows,
            "execution_eligible":False,
            "promotion_eligible":False,
        }

    def close(self)->None:
        self.conn.close()
