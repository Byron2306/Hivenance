from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Optional

from .adversarial_validation import AdversarialValidator


class ValidationLabAgent:
    """Phase-4 adversarial validation agent.

    It consumes Phase-3 simulation evidence only. It cannot import or invoke a
    private exchange client, cannot mutate live balances, and cannot promote a
    strategy without human review.
    """

    def __init__(
        self,
        cfg: Any,
        execution_lab: Any,
        data_store: Any,
        coordinator: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg
        self.execution_lab = execution_lab
        self.data_store = data_store
        self.coordinator = coordinator
        self.enabled = bool(getattr(cfg, "phase4_validation_enabled", True))
        self.interval_sec = max(60, int(getattr(cfg, "phase4_interval_sec", 900) or 900))
        self.max_rows = max(100, int(getattr(cfg, "phase4_max_rows", 100000) or 100000))
        self.validator = AdversarialValidator(cfg)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._run_count = 0
        self._last_error: Optional[str] = None
        self._latest: dict[str, Any] = {
            "phase": 4,
            "mode": "adversarial_validation_only",
            "status": "INITIALIZED" if self.enabled else "DISABLED",
            "execution_wired": False,
            "real_orders_submitted": 0,
        }

    def start(self) -> bool:
        if not self.enabled or self.data_store is None:
            with self._lock:
                self._latest["status"] = "UNAVAILABLE"
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hivenance-validation-lab", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.0, timeout))

    def status(self) -> dict[str, Any]:
        with self._lock:
            status = self._latest.get("status", "UNKNOWN")
        return {
            "phase": 4,
            "mode": "adversarial_validation_only",
            "enabled": self.enabled,
            "status": status,
            "run_count": self._run_count,
            "last_error": self._last_error,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "execution_wired": False,
            "real_orders_submitted": 0,
        }

    def latest_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._latest, default=str))

    def _publish(self, key: str, payload: dict[str, Any]) -> None:
        if self.coordinator and hasattr(self.coordinator, "share_data"):
            self.coordinator.share_data(key, {
                "buzz": {"type": key, "source": "VALIDATION_LAB", "ts": int(time.time() * 1000)},
                "payload": payload,
            })

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.run_once()
                self._last_error = None
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logging.exception("Validation lab cycle failed")
                with self._lock:
                    self._latest["status"] = "ERROR"
            self._stop.wait(max(1.0, self.interval_sec - (time.monotonic() - started)))

    def run_once(self, *, drive_phase3: bool = True) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("phase4 validation lab is disabled")
        started_ts = time.time()
        run_id = f"val-{int(started_ts * 1000)}-{uuid.uuid4().hex[:8]}"
        phase3_payload = None
        if drive_phase3 and self.execution_lab is not None:
            phase3_payload = self.execution_lab.run_once(drive_phase2=True)
        rows = self.data_store.get_phase4_validation_dataset(limit=self.max_rows)
        report = self.validator.validate(rows, run_id=run_id)
        completed_ts = time.time()
        report["started_ts"] = started_ts
        report["completed_ts"] = completed_ts
        report["phase3_cycle"] = phase3_payload
        report["dataset_hash"] = hashlib.sha256(
            json.dumps({
                "validator_version": self.validator.version,
                "rows": rows,
                "candidate_results": report.get("candidate_results"),
            }, sort_keys=True, default=str).encode()
        ).hexdigest()
        if not self.data_store.persist_phase4_validation_report(report):
            raise RuntimeError("failed to persist Phase-4 validation report")
        with self._lock:
            self._latest = report
            self._run_count += 1
        self._publish("buzz.validation_lab.snapshot", report)
        self._publish("buzz.validation_lab.health", {
            "phase": 4,
            "status": report.get("status"),
            "run_id": run_id,
            "candidate_count": report.get("candidate_count", 0),
            "ready_for_phase5_review": bool((report.get("readiness") or {}).get("ready_for_phase5_review")),
            "execution_wired": False,
            "real_orders_submitted": 0,
        })
        return report
