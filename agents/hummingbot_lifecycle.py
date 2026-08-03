import json
import os
import subprocess
import time
import uuid
from typing import Any, Dict, Optional

from agents.hummingbot_strategy_v2 import HummingbotV2IntentAdapter


class HummingbotExecutorLifecycle:
    """Plan-first Hummingbot executor lifecycle manager.

    The default mode is sidecar-safe: lifecycle states are persisted and exposed to
    the UI, while external Hummingbot processes are not started unless explicitly
    enabled in config.
    """

    TERMINAL_STATES = {"STOPPED", "CLOSED", "FAILED"}

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.cfg = cfg
        self.coordinator = coordinator
        self.adapter = HummingbotV2IntentAdapter(cfg)
        self._processes: Dict[str, subprocess.Popen] = {}

    def status(self) -> Dict[str, Any]:
        live_enabled = bool(getattr(self.cfg, "hummingbot_sidecar_live_enabled", False))
        return {
            "name": "HUMMINGBOT_EXECUTOR_LIFECYCLE",
            "enabled": True,
            "mode": "sidecar_live" if live_enabled else "plan_persist_only",
            "live_enabled": live_enabled,
            "states": self.list(),
            "commands": ["create", "monitor", "stop", "retry", "close"],
        }

    def create(self, executor_type: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        intent = dict(intent or {})
        plan = self.adapter.plan(intent, executor_type=executor_type)
        now = time.time()
        executor_id = intent.get("executor_id") or f"hb-{int(now * 1000)}-{uuid.uuid4().hex[:8]}"
        payload = {
            "ok": bool(plan.get("ok")),
            "executor_id": executor_id,
            "executor_type": plan.get("executor_type") or executor_type,
            "symbol": intent.get("symbol") or getattr(self.cfg, "symbol", None),
            "side": intent.get("side") or intent.get("action"),
            "state": "CREATED" if plan.get("ok") else "FAILED",
            "attempts": 1 if plan.get("ok") else 0,
            "created_ts": now,
            "updated_ts": now,
            "reason": plan.get("reason"),
            "intent": intent,
            "config": plan.get("config") or {},
            "plan": plan,
        }
        if plan.get("ok") and bool(getattr(self.cfg, "hummingbot_sidecar_live_enabled", False)):
            started = self._start_sidecar(executor_id, payload)
            payload.update(started)
        self._persist(payload)
        self._share("buzz.hummingbot.lifecycle", payload)
        return payload

    def monitor(self, executor_id: Optional[str] = None) -> Dict[str, Any]:
        states = self.list(executor_id=executor_id)
        now = time.time()
        updates = {}
        for eid, state in states.items():
            updated = dict(state)
            proc = self._processes.get(eid)
            if proc is not None:
                code = proc.poll()
                if code is None:
                    updated["state"] = "RUNNING"
                    updated["process_status"] = "running"
                elif code == 0:
                    updated["state"] = "CLOSED"
                    updated["process_status"] = "exited_0"
                    updated["stopped_ts"] = now
                else:
                    updated["state"] = "FAILED"
                    updated["process_status"] = f"exited_{code}"
                    updated["stopped_ts"] = now
            elif updated.get("state") == "CREATED":
                updated["state"] = "READY"
                updated["process_status"] = "not_started"
            updated["updated_ts"] = now
            self._persist(updated)
            updates[eid] = updated
        return {"ok": True, "executors": updates}

    def stop(self, executor_id: str, reason: str = "operator_stop") -> Dict[str, Any]:
        payload = self._one(executor_id)
        if not payload:
            return {"ok": False, "executor_id": executor_id, "error": "executor_not_found"}
        proc = self._processes.get(executor_id)
        if proc is not None and proc.poll() is None:
            proc.terminate()
        payload.update({
            "state": "STOPPED",
            "reason": reason,
            "updated_ts": time.time(),
            "stopped_ts": time.time(),
        })
        self._persist(payload)
        self._share("buzz.hummingbot.lifecycle", payload)
        return {"ok": True, "executor": payload}

    def close(self, executor_id: str, reason: str = "operator_close") -> Dict[str, Any]:
        stopped = self.stop(executor_id, reason=reason)
        if not stopped.get("ok"):
            return stopped
        payload = stopped.get("executor") or {}
        payload["state"] = "CLOSED"
        payload["updated_ts"] = time.time()
        self._persist(payload)
        self._share("buzz.hummingbot.lifecycle", payload)
        return {"ok": True, "executor": payload}

    def retry(self, executor_id: str) -> Dict[str, Any]:
        payload = self._one(executor_id)
        if not payload:
            return {"ok": False, "executor_id": executor_id, "error": "executor_not_found"}
        if payload.get("state") not in self.TERMINAL_STATES and payload.get("state") != "READY":
            return {"ok": False, "executor_id": executor_id, "error": "executor_not_retryable", "state": payload.get("state")}
        intent = dict(payload.get("intent") or {})
        intent["executor_id"] = executor_id
        new_payload = self.create(payload.get("executor_type") or "position", intent)
        new_payload["attempts"] = int(payload.get("attempts") or 0) + 1
        new_payload["created_ts"] = payload.get("created_ts") or new_payload.get("created_ts")
        new_payload["state"] = "RETRYING" if not bool(getattr(self.cfg, "hummingbot_sidecar_live_enabled", False)) else new_payload.get("state")
        self._persist(new_payload)
        return {"ok": True, "executor": new_payload}

    def list(self, executor_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        ds = self._ds()
        if ds and hasattr(ds, "get_hummingbot_lifecycle"):
            return ds.get_hummingbot_lifecycle(executor_id=executor_id, limit=limit)
        return {}

    def _start_sidecar(self, executor_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        template = str(getattr(self.cfg, "hummingbot_sidecar_command", "") or "")
        if not template:
            return {"state": "READY", "process_status": "command_not_configured"}
        config_path = self._write_executor_config(executor_id, payload)
        command = template.format(executor_id=executor_id, config_path=config_path)
        try:
            env = os.environ.copy()
            env["HIVENANCE_HB_EXECUTOR_ID"] = executor_id
            env["HIVENANCE_HB_CONFIG_PATH"] = config_path
            proc = subprocess.Popen(command, shell=True, env=env)
            self._processes[executor_id] = proc
            return {"state": "RUNNING", "pid": proc.pid, "process_status": "started", "config_path": config_path}
        except Exception as e:
            return {"state": "FAILED", "process_status": f"start_error:{e}", "config_path": config_path}

    def _write_executor_config(self, executor_id: str, payload: Dict[str, Any]) -> str:
        root = os.path.abspath(getattr(self.cfg, "hummingbot_sidecar_config_dir", "data/hummingbot_executors") or "data/hummingbot_executors")
        os.makedirs(root, exist_ok=True)
        path = os.path.join(root, f"{executor_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        return path

    def _one(self, executor_id: str) -> Dict[str, Any]:
        return (self.list(executor_id=executor_id) or {}).get(executor_id) or {}

    def _persist(self, payload: Dict[str, Any]) -> None:
        ds = self._ds()
        if ds and hasattr(ds, "upsert_hummingbot_lifecycle"):
            ds.upsert_hummingbot_lifecycle(payload)

    def _share(self, typ: str, payload: Dict[str, Any]) -> None:
        try:
            if self.coordinator:
                self.coordinator.share_data(typ, {
                    "buzz": {"type": typ, "source": "HUMMINGBOT_LIFECYCLE", "ts": int(time.time() * 1000)},
                    "payload": payload,
                })
        except Exception:
            pass

    def _ds(self):
        try:
            return self.coordinator.agents.get("data_store") if self.coordinator else None
        except Exception:
            return None
