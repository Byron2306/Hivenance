from __future__ import annotations

import json
import time
from typing import Any, Mapping, Optional


class GrowthStore:
    """Durable Phase-7 controlled-growth projections.

    This store never submits orders. It records stage proposals, approvals,
    evidence windows, demotions and incidents. Actual canary authority remains
    inside the isolated Phase-6 operator path and receives only a derived,
    stage-capped configuration from the Phase-7 runner.
    """

    def __init__(self, data_store: Any) -> None:
        self.data_store = data_store
        self.conn = getattr(data_store, "conn", None)
        self._lock = getattr(data_store, "_lock", None)
        if self.conn is None:
            raise RuntimeError("Phase-7 requires an available authoritative data store")
        self._create_tables()

    def _create_tables(self) -> None:
        lock = self._lock
        if lock:
            lock.acquire()
        try:
            c = self.conn.cursor()
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase7_growth_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                state TEXT,
                reason TEXT,
                current_stage INTEGER DEFAULT 0,
                stage_started_ts REAL,
                stage_start_round_trips INTEGER DEFAULT 0,
                envelope_hash TEXT,
                updated_ts REAL,
                human_review_required INTEGER DEFAULT 1,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase7_growth_proposals (
                proposal_id TEXT PRIMARY KEY,
                from_stage INTEGER,
                to_stage INTEGER,
                proposed_by TEXT,
                created_ts REAL,
                cooldown_until_ts REAL,
                expires_ts REAL,
                evidence_hash TEXT,
                config_hash TEXT,
                evidence TEXT,
                reasons TEXT,
                status TEXT,
                approved_ts REAL,
                activated_ts REAL,
                rejected_ts REAL,
                rejection_reason TEXT,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase7_proposal_status ON phase7_growth_proposals(status, created_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase7_growth_approvals (
                approval_id TEXT PRIMARY KEY,
                proposal_id TEXT,
                approved_by TEXT,
                approved_ts REAL,
                expires_ts REAL,
                acknowledgement_hash TEXT,
                status TEXT,
                consumed_ts REAL,
                revoked_ts REAL,
                revoke_reason TEXT,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase7_growth_windows (
                window_id TEXT PRIMARY KEY,
                stage_id INTEGER,
                stage_name TEXT,
                started_ts REAL,
                ended_ts REAL,
                start_round_trips INTEGER,
                end_round_trips INTEGER,
                status TEXT,
                envelope_hash TEXT,
                evidence_hash TEXT,
                result TEXT,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase7_growth_incidents (
                incident_id TEXT PRIMARY KEY,
                ts REAL,
                severity TEXT,
                category TEXT,
                message TEXT,
                stage_id INTEGER,
                requires_human_review INTEGER,
                resolved INTEGER DEFAULT 0,
                resolved_ts REAL,
                resolution TEXT,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase7_incidents_open ON phase7_growth_incidents(resolved, severity, ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase7_growth_audit (
                audit_id TEXT PRIMARY KEY,
                ts REAL,
                action TEXT,
                actor TEXT,
                state_before TEXT,
                state_after TEXT,
                payload TEXT
            )
            ''')
            self.conn.commit()
        finally:
            if lock:
                lock.release()

    @staticmethod
    def _decode(row: Any, columns: list[str]) -> dict[str, Any]:
        data = dict(zip(columns, row))
        for key in ("payload", "evidence", "reasons", "result"):
            raw = data.get(key)
            if isinstance(raw, str) and raw:
                try:
                    data[key] = json.loads(raw)
                except Exception:
                    pass
        for key in ("human_review_required", "requires_human_review", "resolved"):
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

    def get_state(self) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM phase7_growth_state WHERE singleton=1")
        if not row:
            return {
                "state": "LOCKED",
                "reason": "no_phase7_stage_activated",
                "current_stage": 0,
                "stage_started_ts": None,
                "stage_start_round_trips": 0,
                "human_review_required": True,
            }
        return row

    def set_state(
        self,
        state: str,
        reason: str,
        *,
        current_stage: Optional[int] = None,
        stage_started_ts: Optional[float] = None,
        stage_start_round_trips: Optional[int] = None,
        envelope_hash: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        before = self.get_state()
        stage = int(before.get("current_stage", 0) if current_stage is None else current_stage)
        started = before.get("stage_started_ts") if stage_started_ts is None else stage_started_ts
        start_rt = int(before.get("stage_start_round_trips", 0) if stage_start_round_trips is None else stage_start_round_trips)
        env_hash = before.get("envelope_hash") if envelope_hash is None else envelope_hash
        now = time.time()
        body = dict(payload or {})
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase7_growth_state
                (singleton,state,reason,current_stage,stage_started_ts,stage_start_round_trips,
                 envelope_hash,updated_ts,human_review_required,payload)
                VALUES (1,?,?,?,?,?,?,?,?,?)""",
                (state, reason, stage, started, start_rt, env_hash, now, 1, json.dumps(body, sort_keys=True, default=str)),
            )
            self.conn.commit()
        self.audit("STATE_CHANGE", "SYSTEM", before, self.get_state(), {"reason": reason})

    def audit(self, action: str, actor: str, before: Mapping[str, Any], after: Mapping[str, Any], payload: Optional[Mapping[str, Any]] = None) -> None:
        import hashlib
        now = time.time()
        body = {"action": action, "actor": actor, "ts": now, "payload": dict(payload or {})}
        audit_id = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO phase7_growth_audit (audit_id,ts,action,actor,state_before,state_after,payload) VALUES (?,?,?,?,?,?,?)",
                (audit_id, now, action, actor, json.dumps(dict(before), sort_keys=True, default=str),
                 json.dumps(dict(after), sort_keys=True, default=str), json.dumps(body, sort_keys=True, default=str)),
            )
            self.conn.commit()

    def persist_proposal(self, proposal: Mapping[str, Any]) -> bool:
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO phase7_growth_proposals
                (proposal_id,from_stage,to_stage,proposed_by,created_ts,cooldown_until_ts,expires_ts,
                 evidence_hash,config_hash,evidence,reasons,status,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    proposal.get("proposal_id"), proposal.get("from_stage"), proposal.get("to_stage"),
                    proposal.get("proposed_by"), proposal.get("created_ts"), proposal.get("cooldown_until_ts"),
                    proposal.get("expires_ts"), proposal.get("evidence_hash"), proposal.get("config_hash"),
                    json.dumps(proposal.get("evidence") or {}, sort_keys=True, default=str),
                    json.dumps(proposal.get("reasons") or [], sort_keys=True, default=str), proposal.get("status", "PROPOSED"),
                    json.dumps(dict(proposal), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()
            return bool(cur.rowcount)

    def latest_proposal(self) -> dict[str, Any]:
        return self._fetchone("SELECT * FROM phase7_growth_proposals ORDER BY created_ts DESC LIMIT 1")

    def active_proposal(self) -> dict[str, Any]:
        return self._fetchone("SELECT * FROM phase7_growth_proposals WHERE status IN ('PROPOSED','APPROVED') ORDER BY created_ts DESC LIMIT 1")

    def mark_proposal_approved(self, proposal_id: str, approved_ts: float) -> None:
        with self._lock:
            self.conn.execute("UPDATE phase7_growth_proposals SET status='APPROVED', approved_ts=? WHERE proposal_id=? AND status='PROPOSED'", (approved_ts, proposal_id))
            self.conn.commit()

    def mark_proposal_activated(self, proposal_id: str, activated_ts: float) -> None:
        with self._lock:
            self.conn.execute("UPDATE phase7_growth_proposals SET status='ACTIVATED', activated_ts=? WHERE proposal_id=? AND status='APPROVED'", (activated_ts, proposal_id))
            self.conn.commit()

    def reject_active_proposals(self, reason: str, now_ts: Optional[float] = None) -> int:
        now = float(now_ts or time.time())
        with self._lock:
            cur = self.conn.execute(
                "UPDATE phase7_growth_proposals SET status='REJECTED', rejected_ts=?, rejection_reason=? WHERE status IN ('PROPOSED','APPROVED')",
                (now, reason),
            )
            self.conn.commit()
            return int(cur.rowcount or 0)

    def persist_approval(self, approval: Mapping[str, Any]) -> bool:
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO phase7_growth_approvals
                (approval_id,proposal_id,approved_by,approved_ts,expires_ts,acknowledgement_hash,status,payload)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    approval.get("approval_id"), approval.get("proposal_id"), approval.get("approved_by"),
                    approval.get("approved_ts"), approval.get("expires_ts"), approval.get("acknowledgement_hash"),
                    approval.get("status", "ACTIVE"), json.dumps(dict(approval), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()
            return bool(cur.rowcount)

    def active_approval(self, now_ts: Optional[float] = None) -> dict[str, Any]:
        now = float(now_ts or time.time())
        return self._fetchone(
            "SELECT * FROM phase7_growth_approvals WHERE status='ACTIVE' AND expires_ts>? ORDER BY approved_ts DESC LIMIT 1",
            (now,),
        )

    def consume_approval(self, approval_id: str, now_ts: Optional[float] = None) -> None:
        now = float(now_ts or time.time())
        with self._lock:
            self.conn.execute("UPDATE phase7_growth_approvals SET status='CONSUMED', consumed_ts=? WHERE approval_id=? AND status='ACTIVE'", (now, approval_id))
            self.conn.commit()

    def revoke_approval(self, reason: str, now_ts: Optional[float] = None) -> int:
        now = float(now_ts or time.time())
        with self._lock:
            cur = self.conn.execute(
                "UPDATE phase7_growth_approvals SET status='REVOKED', revoked_ts=?, revoke_reason=? WHERE status='ACTIVE'",
                (now, reason),
            )
            self.conn.commit()
            return int(cur.rowcount or 0)

    def start_window(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO phase7_growth_windows
                (window_id,stage_id,stage_name,started_ts,ended_ts,start_round_trips,end_round_trips,status,
                 envelope_hash,evidence_hash,result,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.get("window_id"), record.get("stage_id"), record.get("stage_name"),
                    record.get("started_ts"), record.get("ended_ts"), record.get("start_round_trips"),
                    record.get("end_round_trips"), record.get("status", "ACTIVE"), record.get("envelope_hash"),
                    record.get("evidence_hash"), json.dumps(record.get("result") or {}, sort_keys=True, default=str),
                    json.dumps(dict(record), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def close_active_window(self, result: Mapping[str, Any], *, status: str, now_ts: Optional[float] = None) -> None:
        now = float(now_ts or time.time())
        active = self._fetchone("SELECT * FROM phase7_growth_windows WHERE status='ACTIVE' ORDER BY started_ts DESC LIMIT 1")
        if not active:
            return
        with self._lock:
            self.conn.execute(
                "UPDATE phase7_growth_windows SET status=?, ended_ts=?, end_round_trips=?, evidence_hash=?, result=? WHERE window_id=?",
                (status, now, int(result.get("completed_round_trips", 0)), result.get("evidence_hash"),
                 json.dumps(dict(result), sort_keys=True, default=str), active.get("window_id")),
            )
            self.conn.commit()

    def windows(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase7_growth_windows ORDER BY started_ts DESC LIMIT ?", (int(limit),))

    def persist_incident(self, incident: Mapping[str, Any]) -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR IGNORE INTO phase7_growth_incidents
                (incident_id,ts,severity,category,message,stage_id,requires_human_review,resolved,payload)
                VALUES (?,?,?,?,?,?,?,0,?)""",
                (
                    incident.get("incident_id"), incident.get("ts"), incident.get("severity"),
                    incident.get("category"), incident.get("message"), incident.get("stage_id", 0),
                    int(bool(incident.get("requires_human_review", True))), json.dumps(dict(incident), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()

    def open_incidents(self) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase7_growth_incidents WHERE resolved=0 ORDER BY ts DESC")

    def resolve_incident(self, incident_id: str, resolution: str, now_ts: Optional[float] = None) -> bool:
        now = float(now_ts or time.time())
        incident_id = str(incident_id or "").strip()
        resolution = str(resolution or "").strip()
        if not incident_id or not resolution:
            return False
        with self._lock:
            cur = self.conn.execute(
                "UPDATE phase7_growth_incidents SET resolved=1, resolved_ts=?, resolution=? WHERE incident_id=? AND resolved=0",
                (now, resolution, incident_id),
            )
            self.conn.commit()
            return bool(cur.rowcount)

    def proposals(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase7_growth_proposals ORDER BY created_ts DESC LIMIT ?", (int(limit),))

    def approvals(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase7_growth_approvals ORDER BY approved_ts DESC LIMIT ?", (int(limit),))

    def audit_rows(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._fetchall("SELECT * FROM phase7_growth_audit ORDER BY ts DESC LIMIT ?", (int(limit),))
