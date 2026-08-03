from __future__ import annotations

import json
import time
from typing import Any, Iterable, Mapping, Optional


class CanaryStore:
    """Phase-6 projections sharing the authoritative SQLite connection.

    The adapter deliberately does not write to the legacy live ``orders`` or
    ``fills`` tables. Phase-6 evidence has its own immutable-ish projections so
    canary authority cannot silently leak into the old execution path.
    """

    def __init__(self, data_store: Any) -> None:
        self.data_store = data_store
        self.conn = getattr(data_store, "conn", None)
        self._lock = getattr(data_store, "_lock", None)
        if self.conn is None:
            raise RuntimeError("Phase-6 requires an available authoritative data store")
        self._create_tables()

    def _create_tables(self) -> None:
        lock = self._lock
        if lock:
            lock.acquire()
        try:
            c = self.conn.cursor()
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                state TEXT,
                reason TEXT,
                updated_ts REAL,
                human_review_required INTEGER DEFAULT 1,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_approvals (
                approval_id TEXT PRIMARY KEY,
                freeze_id TEXT,
                phase4_run_id TEXT,
                candidate_key TEXT,
                model_id TEXT,
                order_policy TEXT,
                approved_by TEXT,
                approved_ts REAL,
                expires_ts REAL,
                allowed_symbols TEXT,
                max_notional_usd REAL,
                max_entry_orders INTEGER,
                config_hash TEXT,
                acknowledgement_hash TEXT,
                live_submission_authorized INTEGER,
                status TEXT,
                consumed_entry_orders INTEGER DEFAULT 0,
                automatic_scaling INTEGER DEFAULT 0,
                leverage INTEGER DEFAULT 1,
                revoked_ts REAL,
                revoke_reason TEXT,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase6_approval_status_expiry ON phase6_canary_approvals(status, expires_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                status TEXT,
                state TEXT,
                approval_id TEXT,
                reconciled INTEGER,
                validate_only_calls INTEGER,
                live_submission_attempts INTEGER,
                live_orders_submitted INTEGER,
                exits_submitted INTEGER,
                incidents_created INTEGER,
                dataset_hash TEXT,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_intents (
                canary_intent_id TEXT PRIMARY KEY,
                shadow_intent_id TEXT UNIQUE,
                forecast_id TEXT,
                approval_id TEXT,
                freeze_id TEXT,
                client_order_id TEXT UNIQUE,
                venue TEXT,
                symbol TEXT,
                side TEXT,
                order_type TEXT,
                time_in_force TEXT,
                quantity REAL,
                notional_usd REAL,
                reference_price REAL,
                limit_price REAL,
                stop_price REAL,
                target_price REAL,
                horizon_ts REAL,
                predicted_cost_bps REAL,
                predicted_net_bps REAL,
                probability_positive_net REAL,
                data_quality REAL,
                spread_bps REAL,
                created_ts REAL,
                deadline_rfc3339 TEXT,
                config_hash TEXT,
                live_submission_requested INTEGER,
                validate_only_completed INTEGER,
                status TEXT,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase6_intents_created ON phase6_canary_intents(created_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_orders (
                client_order_id TEXT PRIMARY KEY,
                canary_intent_id TEXT,
                exchange_order_id TEXT,
                symbol TEXT,
                side TEXT,
                status TEXT,
                quantity REAL,
                limit_price REAL,
                filled_quantity REAL,
                average_fill_price REAL,
                cost_quote REAL,
                fee_quote REAL,
                created_ts REAL,
                updated_ts REAL,
                raw_status TEXT,
                live_submitted INTEGER,
                reconciled INTEGER,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase6_orders_status ON phase6_canary_orders(status, updated_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_positions (
                position_id TEXT PRIMARY KEY,
                entry_client_order_id TEXT UNIQUE,
                symbol TEXT,
                quantity REAL,
                entry_price REAL,
                entry_cost_quote REAL,
                opened_ts REAL,
                stop_price REAL,
                target_price REAL,
                horizon_ts REAL,
                status TEXT,
                exit_client_order_id TEXT,
                exit_price REAL,
                closed_ts REAL,
                realized_pnl_quote REAL,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase6_positions_status ON phase6_canary_positions(status, opened_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_incidents (
                incident_id TEXT PRIMARY KEY,
                ts REAL,
                severity TEXT,
                category TEXT,
                message TEXT,
                symbol TEXT,
                client_order_id TEXT,
                requires_human_review INTEGER,
                resolved INTEGER DEFAULT 0,
                resolved_ts REAL,
                resolution TEXT,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase6_incidents_open ON phase6_canary_incidents(resolved, severity, ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_canary_reconciliations (
                reconciliation_id TEXT PRIMARY KEY,
                ts REAL,
                status TEXT,
                open_orders_count INTEGER,
                canary_open_orders_count INTEGER,
                unknown_orders_count INTEGER,
                active_positions_count INTEGER,
                balance_snapshot TEXT,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase6_deadman_heartbeats (
                heartbeat_id TEXT PRIMARY KEY,
                ts REAL,
                timeout_sec INTEGER,
                status TEXT,
                payload TEXT
            )
            ''')
            self.conn.commit()
        finally:
            if lock:
                lock.release()

    @staticmethod
    def _decode(row: Any, columns: Iterable[str]) -> dict[str, Any]:
        data = dict(zip(columns, row))
        try:
            payload = json.loads(data.get("payload") or "{}")
            if isinstance(payload, dict):
                data.update(payload)
        except Exception:
            pass
        if "allowed_symbols" in data and isinstance(data.get("allowed_symbols"), str):
            try:
                data["allowed_symbols"] = json.loads(data["allowed_symbols"])
            except Exception:
                data["allowed_symbols"] = []
        for key in (
            "live_submission_authorized", "automatic_scaling", "validate_only_completed",
            "live_submission_requested", "live_submitted", "reconciled",
            "human_review_required", "resolved",
        ):
            if key in data and data[key] is not None:
                data[key] = bool(data[key])
        return data

    def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
        c = self.conn.cursor()
        c.execute(query, params)
        row = c.fetchone()
        if not row:
            return {}
        return self._decode(row, [item[0] for item in c.description])

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        c = self.conn.cursor()
        c.execute(query, params)
        cols = [item[0] for item in c.description]
        return [self._decode(row, cols) for row in c.fetchall()]

    def set_state(self, state: str, reason: str, *, payload: Optional[Mapping[str, Any]] = None) -> None:
        now = time.time()
        body = dict(payload or {})
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase6_canary_state
                (singleton,state,reason,updated_ts,human_review_required,payload)
                VALUES (1,?,?,?,?,?)""",
                (state, reason, now, 1, json.dumps(body, sort_keys=True, default=str)),
            )
            self.conn.commit()

    def get_state(self) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM phase6_canary_state WHERE singleton=1")
        if not row:
            return {"state": "DISARMED", "reason": "no_state_record", "human_review_required": True}
        return row

    def persist_approval(self, approval: Mapping[str, Any]) -> bool:
        symbols = list(approval.get("allowed_symbols") or [])
        with self._lock:
            c = self.conn.cursor()
            c.execute("UPDATE phase6_canary_approvals SET status='SUPERSEDED' WHERE status='ACTIVE'")
            c.execute(
                """INSERT OR REPLACE INTO phase6_canary_approvals
                (approval_id,freeze_id,phase4_run_id,candidate_key,model_id,order_policy,
                 approved_by,approved_ts,expires_ts,allowed_symbols,max_notional_usd,
                 max_entry_orders,config_hash,acknowledgement_hash,live_submission_authorized,
                 status,consumed_entry_orders,automatic_scaling,leverage,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    approval.get("approval_id"), approval.get("freeze_id"), approval.get("phase4_run_id"),
                    approval.get("candidate_key"), approval.get("model_id"), approval.get("order_policy"),
                    approval.get("approved_by"), approval.get("approved_ts"), approval.get("expires_ts"),
                    json.dumps(symbols), approval.get("max_notional_usd"), approval.get("max_entry_orders"),
                    approval.get("config_hash"), approval.get("acknowledgement_hash"),
                    int(bool(approval.get("live_submission_authorized"))), approval.get("status", "ACTIVE"),
                    0, int(bool(approval.get("automatic_scaling"))), int(approval.get("leverage", 1)),
                    json.dumps(dict(approval), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()
        self.set_state("DISARMED", "approval_recorded_operator_must_start_canary")
        return True

    def get_active_approval(self, now_ts: Optional[float] = None) -> dict[str, Any]:
        now_ts = float(now_ts or time.time())
        with self._lock:
            row = self._fetchone(
                "SELECT * FROM phase6_canary_approvals WHERE status='ACTIVE' ORDER BY approved_ts DESC LIMIT 1"
            )
            if row and float(row.get("expires_ts") or 0.0) <= now_ts:
                self.conn.execute(
                    "UPDATE phase6_canary_approvals SET status='EXPIRED' WHERE approval_id=?",
                    (row.get("approval_id"),),
                )
                self.conn.commit()
                row["status"] = "EXPIRED"
        return row if row.get("status") == "ACTIVE" else {}

    def revoke_approval(self, reason: str) -> bool:
        with self._lock:
            c = self.conn.cursor()
            c.execute(
                "UPDATE phase6_canary_approvals SET status='REVOKED', revoked_ts=?, revoke_reason=? WHERE status='ACTIVE'",
                (time.time(), str(reason or "human_revocation")),
            )
            changed = c.rowcount > 0
            self.conn.commit()
        self.set_state("HALTED", f"approval_revoked:{reason}")
        return changed

    def consume_entry_slot(self, approval_id: str) -> bool:
        with self._lock:
            c = self.conn.cursor()
            c.execute(
                """UPDATE phase6_canary_approvals
                SET consumed_entry_orders=consumed_entry_orders+1
                WHERE approval_id=? AND status='ACTIVE' AND consumed_entry_orders < max_entry_orders""",
                (approval_id,),
            )
            changed = c.rowcount == 1
            self.conn.commit()
            return changed

    def persist_run(self, report: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase6_canary_runs
                (run_id,started_ts,completed_ts,status,state,approval_id,reconciled,
                 validate_only_calls,live_submission_attempts,live_orders_submitted,
                 exits_submitted,incidents_created,dataset_hash,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report.get("run_id"), report.get("started_ts"), report.get("completed_ts"),
                    report.get("status"), report.get("state"), report.get("approval_id"),
                    int(bool(report.get("reconciled"))), int(report.get("validate_only_calls", 0) or 0),
                    int(report.get("live_submission_attempts", 0) or 0),
                    int(report.get("live_orders_submitted", 0) or 0), int(report.get("exits_submitted", 0) or 0),
                    int(report.get("incidents_created", 0) or 0), report.get("dataset_hash"),
                    json.dumps(dict(report), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def persist_intent(self, intent: Mapping[str, Any]) -> bool:
        with self._lock:
            try:
                self.conn.execute(
                    """INSERT INTO phase6_canary_intents
                    (canary_intent_id,shadow_intent_id,forecast_id,approval_id,freeze_id,client_order_id,
                     venue,symbol,side,order_type,time_in_force,quantity,notional_usd,reference_price,
                     limit_price,stop_price,target_price,horizon_ts,predicted_cost_bps,predicted_net_bps,
                     probability_positive_net,data_quality,spread_bps,created_ts,deadline_rfc3339,config_hash,
                     live_submission_requested,validate_only_completed,status,payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        intent.get("canary_intent_id"), intent.get("shadow_intent_id"), intent.get("forecast_id"),
                        intent.get("approval_id"), intent.get("freeze_id"), intent.get("client_order_id"),
                        intent.get("venue"), intent.get("symbol"), intent.get("side"), intent.get("order_type"),
                        intent.get("time_in_force"), intent.get("quantity"), intent.get("notional_usd"),
                        intent.get("reference_price"), intent.get("limit_price"), intent.get("stop_price"),
                        intent.get("target_price"), intent.get("horizon_ts"), intent.get("predicted_cost_bps"),
                        intent.get("predicted_net_bps"), intent.get("probability_positive_net"),
                        intent.get("data_quality"), intent.get("spread_bps"), intent.get("created_ts"),
                        intent.get("deadline_rfc3339"), intent.get("config_hash"),
                        int(bool(intent.get("live_submission_requested"))),
                        int(bool(intent.get("validate_only_completed"))), intent.get("status", "PERSISTED"),
                        json.dumps(dict(intent), sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
                return True
            except Exception as exc:
                if "UNIQUE constraint" in str(exc):
                    return False
                raise

    def mark_intent(self, canary_intent_id: str, *, status: str, validate_only_completed: Optional[bool] = None) -> None:
        fields = ["status=?"]
        values: list[Any] = [status]
        if validate_only_completed is not None:
            fields.append("validate_only_completed=?")
            values.append(int(bool(validate_only_completed)))
        values.append(canary_intent_id)
        with self._lock:
            self.conn.execute(f"UPDATE phase6_canary_intents SET {', '.join(fields)} WHERE canary_intent_id=?", tuple(values))
            self.conn.commit()

    def next_shadow_candidate(self, *, model_id: str, allowed_symbols: Iterable[str], max_age_sec: int,
                              now_ts: Optional[float] = None) -> dict[str, Any]:
        now_ts = float(now_ts or time.time())
        symbols = [str(item) for item in allowed_symbols]
        if not symbols:
            return {}
        placeholders = ",".join("?" for _ in symbols)
        params: list[Any] = [model_id, now_ts - max(1, int(max_age_sec)), *symbols]
        query = f"""
        SELECT s.* FROM phase5_shadow_intents s
        LEFT JOIN phase6_canary_intents c ON c.shadow_intent_id=s.shadow_intent_id
        WHERE s.model_id=? AND s.created_ts>=? AND s.direction='UP'
          AND s.transmission_status='NEVER_TRANSMITTED' AND s.live_eligible=0
          AND s.symbol IN ({placeholders}) AND c.shadow_intent_id IS NULL
        ORDER BY s.created_ts ASC LIMIT 1
        """
        return self._fetchone(query, tuple(params))

    def persist_order(self, order: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase6_canary_orders
                (client_order_id,canary_intent_id,exchange_order_id,symbol,side,status,quantity,
                 limit_price,filled_quantity,average_fill_price,cost_quote,fee_quote,created_ts,
                 updated_ts,raw_status,live_submitted,reconciled,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    order.get("client_order_id"), order.get("canary_intent_id"), order.get("exchange_order_id"),
                    order.get("symbol"), order.get("side"), order.get("status"), order.get("quantity"),
                    order.get("limit_price"), order.get("filled_quantity", 0.0), order.get("average_fill_price"),
                    order.get("cost_quote", 0.0), order.get("fee_quote", 0.0), order.get("created_ts"),
                    order.get("updated_ts"), order.get("raw_status"), int(bool(order.get("live_submitted"))),
                    int(bool(order.get("reconciled"))), json.dumps(dict(order), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def get_orders(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase6_canary_orders ORDER BY updated_ts DESC LIMIT ?", (int(limit),))

    def get_active_orders(self) -> list[dict[str, Any]]:
        return self._fetchall(
            "SELECT * FROM phase6_canary_orders WHERE status IN ('PERSISTED','VALIDATED','SUBMITTED','ACKNOWLEDGED','OPEN','PARTIALLY_FILLED','UNKNOWN') ORDER BY created_ts"
        )

    def persist_position(self, position: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase6_canary_positions
                (position_id,entry_client_order_id,symbol,quantity,entry_price,entry_cost_quote,opened_ts,
                 stop_price,target_price,horizon_ts,status,exit_client_order_id,exit_price,closed_ts,
                 realized_pnl_quote,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    position.get("position_id"), position.get("entry_client_order_id"), position.get("symbol"),
                    position.get("quantity"), position.get("entry_price"), position.get("entry_cost_quote"),
                    position.get("opened_ts"), position.get("stop_price"), position.get("target_price"),
                    position.get("horizon_ts"), position.get("status", "OPEN"), position.get("exit_client_order_id"),
                    position.get("exit_price"), position.get("closed_ts"), position.get("realized_pnl_quote"),
                    json.dumps(dict(position), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def get_open_position(self) -> dict[str, Any]:
        return self._fetchone("SELECT * FROM phase6_canary_positions WHERE status IN ('OPEN','EXIT_PENDING','UNKNOWN') ORDER BY opened_ts LIMIT 1")

    def get_positions(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase6_canary_positions ORDER BY opened_ts DESC LIMIT ?", (int(limit),))

    def persist_incident(self, incident: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR IGNORE INTO phase6_canary_incidents
                (incident_id,ts,severity,category,message,symbol,client_order_id,
                 requires_human_review,resolved,payload)
                VALUES (?,?,?,?,?,?,?,?,0,?)""",
                (
                    incident.get("incident_id"), incident.get("ts"), incident.get("severity"),
                    incident.get("category"), incident.get("message"), incident.get("symbol"),
                    incident.get("client_order_id"), int(bool(incident.get("requires_human_review", True))),
                    json.dumps(dict(incident), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def open_incidents(self) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase6_canary_incidents WHERE resolved=0 ORDER BY ts DESC")

    def persist_reconciliation(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase6_canary_reconciliations
                (reconciliation_id,ts,status,open_orders_count,canary_open_orders_count,
                 unknown_orders_count,active_positions_count,balance_snapshot,payload)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    record.get("reconciliation_id"), record.get("ts"), record.get("status"),
                    record.get("open_orders_count", 0), record.get("canary_open_orders_count", 0),
                    record.get("unknown_orders_count", 0), record.get("active_positions_count", 0),
                    json.dumps(record.get("balance_snapshot") or {}, sort_keys=True, default=str),
                    json.dumps(dict(record), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def persist_deadman(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase6_deadman_heartbeats
                (heartbeat_id,ts,timeout_sec,status,payload) VALUES (?,?,?,?,?)""",
                (
                    record.get("heartbeat_id"), record.get("ts"), record.get("timeout_sec"),
                    record.get("status"), json.dumps(dict(record), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase6_canary_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit),))

    def approvals(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase6_canary_approvals ORDER BY approved_ts DESC LIMIT ?", (int(limit),))

    def reconciliations(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase6_canary_reconciliations ORDER BY ts DESC LIMIT ?", (int(limit),))

    def active_order_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM phase6_canary_orders WHERE status IN "
            "('PERSISTED','VALIDATED','SUBMITTED','ACKNOWLEDGED','OPEN','PARTIALLY_FILLED','UNKNOWN')"
        ).fetchone()
        return int((row or [0])[0] or 0)

    def active_position_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM phase6_canary_positions WHERE status IN ('OPEN','EXIT_PENDING','UNKNOWN')"
        ).fetchone()
        return int((row or [0])[0] or 0)

    def realized_pnl_utc_day(self, now_ts: Optional[float] = None) -> float:
        now_ts = float(now_ts or time.time())
        day_start = float(int(now_ts // 86400) * 86400)
        row = self.conn.execute(
            "SELECT SUM(realized_pnl_quote) FROM phase6_canary_positions "
            "WHERE status='CLOSED' AND closed_ts>=? AND closed_ts<?",
            (day_start, day_start + 86400.0),
        ).fetchone()
        return float((row or [0])[0] or 0.0)

    def scorecard(self) -> dict[str, Any]:
        c = self.conn.cursor()
        completed = c.execute("SELECT COUNT(*) FROM phase6_canary_positions WHERE status='CLOSED'").fetchone()[0]
        open_positions = c.execute("SELECT COUNT(*) FROM phase6_canary_positions WHERE status IN ('OPEN','EXIT_PENDING','UNKNOWN')").fetchone()[0]
        live_orders = c.execute("SELECT COUNT(*) FROM phase6_canary_orders WHERE live_submitted=1").fetchone()[0]
        unknown_orders = c.execute("SELECT COUNT(*) FROM phase6_canary_orders WHERE status='UNKNOWN'").fetchone()[0]
        incidents = c.execute("SELECT COUNT(*) FROM phase6_canary_incidents WHERE resolved=0").fetchone()[0]
        pnl_row = c.execute("SELECT AVG(realized_pnl_quote), SUM(realized_pnl_quote) FROM phase6_canary_positions WHERE status='CLOSED'").fetchone()
        return {
            "phase": 6,
            "mode": "tiny_live_canary",
            "completed_round_trips": int(completed or 0),
            "open_positions": int(open_positions or 0),
            "live_orders_submitted": int(live_orders or 0),
            "unknown_orders": int(unknown_orders or 0),
            "open_incidents": int(incidents or 0),
            "mean_realized_pnl_quote": float((pnl_row or [0])[0] or 0.0),
            "total_realized_pnl_quote": float((pnl_row or [0, 0])[1] or 0.0),
            "daily_realized_pnl_quote": self.realized_pnl_utc_day(),
            "automatic_scaling": False,
        }

    def readiness(self, *, min_round_trips: int = 50) -> dict[str, Any]:
        score = self.scorecard()
        reasons: list[str] = []
        if score["completed_round_trips"] < int(min_round_trips):
            reasons.append("insufficient_reconciled_round_trips")
        if score["unknown_orders"]:
            reasons.append("unknown_order_state_present")
        if score["open_incidents"]:
            reasons.append("unresolved_canary_incidents")
        if score["open_positions"]:
            reasons.append("position_still_open")
        return {
            "phase": 6,
            "ready_for_phase7_review": not reasons,
            "automatic_scaling": False,
            "execution_scale_authorized": False,
            "human_review_required": True,
            "reasons": reasons,
            **score,
        }
