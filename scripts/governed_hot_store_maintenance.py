#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int((conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() or [0])[0] or 0)
    except Exception:
        return 0


def _delete_old_scorecard_snapshots(conn: sqlite3.Connection, *, keep_per_key: int, dry_run: bool) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT rowid, snapshot_key, created_ts
        FROM phase_scorecard_snapshots
        ORDER BY snapshot_key, created_ts DESC
        """
    ).fetchall()
    kept: dict[str, int] = {}
    delete_ids: list[int] = []
    for rowid, key, _created in rows:
        key = str(key or "")
        kept[key] = kept.get(key, 0) + 1
        if kept[key] > max(1, int(keep_per_key)):
            delete_ids.append(int(rowid))
    if delete_ids and not dry_run:
        conn.executemany("DELETE FROM phase_scorecard_snapshots WHERE rowid=?", [(rowid,) for rowid in delete_ids])
    return {
        "table": "phase_scorecard_snapshots",
        "dry_run": dry_run,
        "keep_per_key": max(1, int(keep_per_key)),
        "delete_candidates": len(delete_ids),
        "deleted": 0 if dry_run else len(delete_ids),
    }


# Pure audit/diagnostic-log tables only -- NEVER include statistical evidence tables here
# (hypothesis_forecasts/hypothesis_outcomes/simulated_orders/observation_snapshots/etc.), since
# those feed the phase4/5 readiness gates (e.g. phase4_min_distinct_days=30) and must retain
# long history. Each entry is (table_name, timestamp_column).
AUDIT_LOG_RETENTION_TABLES: list[tuple[str, str]] = [
    ("raw_events", "ts"),
    ("logs", "timestamp"),
    ("event_envelopes", "ts"),
    ("simulated_order_events", "ts"),
]


def _prune_audit_log_table(conn: sqlite3.Connection, table: str, ts_column: str, *, cutoff_ts: float, dry_run: bool) -> dict[str, Any]:
    try:
        (candidates,) = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {ts_column} < ?", (cutoff_ts,)).fetchone()
    except Exception as exc:
        return {"table": table, "ok": False, "reason": str(exc)}
    candidates = int(candidates or 0)
    deleted = 0
    if candidates and not dry_run:
        cur = conn.execute(f"DELETE FROM {table} WHERE {ts_column} < ?", (cutoff_ts,))
        deleted = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else candidates
    return {
        "table": table,
        "ok": True,
        "dry_run": dry_run,
        "cutoff_ts": cutoff_ts,
        "delete_candidates": candidates,
        "deleted": 0 if dry_run else deleted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed hot-store retention and compaction for Hivenance SQLite evidence.")
    parser.add_argument("--database", type=Path, default=ROOT / "data/swarm_data.db")
    parser.add_argument("--receipt", type=Path, default=ROOT / "data/hot_store_maintenance_receipt.json")
    parser.add_argument("--checkpoint", action="store_true", help="Run WAL checkpoint.")
    parser.add_argument("--truncate-wal", action="store_true", help="Use PRAGMA wal_checkpoint(TRUNCATE).")
    parser.add_argument("--compact-scorecards", action="store_true", help="Compact materialized phase scorecard snapshots.")
    parser.add_argument("--keep-scorecards-per-key", type=int, default=3)
    parser.add_argument("--apply-delete", action="store_true", help="Actually delete old compact scorecard snapshots.")
    parser.add_argument("--prune-audit-logs-older-than-days", type=float, default=None, help="Delete rows older than N days from raw_events/logs/event_envelopes/simulated_order_events (dry-run unless --apply-delete is also set).")
    parser.add_argument("--vacuum", action="store_true", help="Run VACUUM after explicit maintenance.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db_path = args.database if args.database.is_absolute() else ROOT / args.database
    store = DataStoreAgent(str(db_path))
    before = store.get_database_pressure_snapshot()
    actions: list[dict[str, Any]] = []
    if args.checkpoint or args.truncate_wal:
        actions.append({"action": "wal_checkpoint", **store.checkpoint_database_wal(truncate=bool(args.truncate_wal))})
    if args.compact_scorecards:
        actions.append(
            {
                "action": "compact_scorecard_snapshots",
                **_delete_old_scorecard_snapshots(
                    store.conn,
                    keep_per_key=max(1, int(args.keep_scorecards_per_key)),
                    dry_run=not bool(args.apply_delete),
                ),
            }
        )
        if args.apply_delete:
            store.conn.commit()
    if args.prune_audit_logs_older_than_days is not None:
        cutoff_ts = time.time() - (float(args.prune_audit_logs_older_than_days) * 86400.0)
        prune_results = [
            _prune_audit_log_table(store.conn, table, ts_column, cutoff_ts=cutoff_ts, dry_run=not bool(args.apply_delete))
            for table, ts_column in AUDIT_LOG_RETENTION_TABLES
        ]
        actions.append({"action": "prune_audit_logs", "retention_days": args.prune_audit_logs_older_than_days, "results": prune_results})
        if args.apply_delete:
            store.conn.commit()
    if args.vacuum:
        if not args.apply_delete:
            actions.append({"action": "vacuum", "ok": False, "reason": "requires_apply_delete"})
        else:
            store.conn.execute("VACUUM")
            actions.append({"action": "vacuum", "ok": True})
    after = store.get_database_pressure_snapshot()
    receipt = {
        "schema": "hivenance_hot_store_maintenance_receipt_v1",
        "authority": "storage_maintenance_only",
        "execution_authority": "none",
        "database": str(db_path),
        "created_ts": time.time(),
        "destructive_delete_enabled": bool(args.apply_delete),
        "before": before,
        "after": after,
        "table_counts": {
            "phase_scorecard_snapshots": _table_count(store.conn, "phase_scorecard_snapshots"),
            "hypothesis_forecasts": _table_count(store.conn, "hypothesis_forecasts"),
            "simulated_orders": _table_count(store.conn, "simulated_orders"),
            "crystal_registry": _table_count(store.conn, "crystal_registry"),
        },
        "actions": actions,
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(receipt, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"MAINTENANCE receipt={args.receipt} "
            f"db={after.get('database_size_bytes')} wal={after.get('wal_size_bytes')} actions={len(actions)}"
        )
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
