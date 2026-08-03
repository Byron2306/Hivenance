from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Optional

from .execution_engine import SCENARIOS, DeterministicExecutionSimulator
from .venue_profiles import POLICIES


class ExecutionLabAgent:
    """Phase-3 execution-aware research lab.

    It may drive Phase 2, settle matured forecasts, and simulate order lifecycles.
    It is structurally unable to submit a private exchange order.
    """

    def __init__(
        self,
        cfg: Any,
        hypothesis_swarm: Any,
        data_store: Any,
        coordinator: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg
        self.hypothesis_swarm = hypothesis_swarm
        self.data_store = data_store
        self.coordinator = coordinator
        self.enabled = bool(getattr(cfg, "phase3_execution_lab_enabled", True))
        self.interval_sec = max(30, int(getattr(cfg, "phase3_interval_sec", 120) or 120))
        self.max_forecasts_per_cycle = max(1, int(getattr(cfg, "phase3_max_forecasts_per_cycle", 50) or 50))
        self.simulator = DeterministicExecutionSimulator(cfg)
        self.policies = tuple(POLICIES)
        self.scenarios = tuple(SCENARIOS)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._run_count = 0
        self._last_error: Optional[str] = None
        self._latest: dict[str, Any] = {
            "phase": 3,
            "mode": "execution_simulation_only",
            "status": "INITIALIZED" if self.enabled else "DISABLED",
            "execution_wired": False,
            "real_orders_submitted": 0,
            "simulations": [],
        }

    def start(self) -> bool:
        if not self.enabled or self.data_store is None or self.hypothesis_swarm is None:
            with self._lock:
                self._latest["status"] = "UNAVAILABLE"
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hivenance-execution-lab", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.0, timeout))

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = dict(self._latest)
        return {
            "phase": 3,
            "mode": "execution_simulation_only",
            "enabled": self.enabled,
            "status": latest.get("status", "UNKNOWN"),
            "run_count": self._run_count,
            "last_error": self._last_error,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "policies": list(self.policies),
            "scenarios": list(self.scenarios),
            "execution_wired": False,
            "real_orders_submitted": 0,
        }

    def latest_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._latest, default=str))

    def _publish(self, key: str, payload: dict[str, Any]) -> None:
        if self.coordinator and hasattr(self.coordinator, "share_data"):
            self.coordinator.share_data(key, {
                "buzz": {"type": key, "source": "EXECUTION_LAB", "ts": int(time.time() * 1000)},
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
                logging.exception("Execution lab cycle failed")
                with self._lock:
                    self._latest["status"] = "ERROR"
            self._stop.wait(max(1.0, self.interval_sec - (time.monotonic() - started)))

    def run_once(self, *, drive_phase2: bool = True) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("phase3 execution lab is disabled")
        started_ms = int(time.time() * 1000)
        run_id = f"sim-{started_ms}-{uuid.uuid4().hex[:8]}"
        phase2_payload = None
        if drive_phase2:
            phase2_payload = self.hypothesis_swarm.run_once()
        settlement = self.data_store.settle_mature_hypothesis_forecasts(
            tolerance_sec=float(getattr(self.cfg, "phase2_settlement_tolerance_sec", 600) or 600)
        )
        candidates = self.data_store.get_phase3_forecast_candidates(limit=self.max_forecasts_per_cycle)
        candidate_meta = (
            self.data_store.get_phase3_candidate_meta()
            if hasattr(self.data_store, "get_phase3_candidate_meta")
            else {}
        )
        simulations = []
        skipped_existing = 0
        for candidate in candidates:
            for policy in self.policies:
                for scenario in self.scenarios:
                    sim_id = hashlib.sha256(
                        f"{candidate.get('forecast_id')}:{policy}:{scenario}:{self.simulator.simulator_version}".encode()
                    ).hexdigest()
                    if self.data_store.simulation_exists(sim_id):
                        skipped_existing += 1
                        continue
                    result = self.simulator.simulate(candidate, run_id=run_id, order_policy=policy, scenario=scenario)
                    row = result.to_dict()
                    if not self.data_store.persist_execution_simulation(row):
                        raise RuntimeError(f"failed to persist simulation {row.get('simulation_id')}")
                    simulations.append(row)

        completed_ms = int(time.time() * 1000)
        summary = {
            "run_id": run_id,
            "started_at_ms": started_ms,
            "completed_at_ms": completed_ms,
            "forecasts_examined": len(candidates),
            "simulations_created": len(simulations),
            "simulations_skipped_existing": skipped_existing,
            "completed": sum(1 for row in simulations if row.get("status") == "COMPLETED"),
            "rejected": sum(1 for row in simulations if row.get("status") == "REJECTED"),
            "expired": sum(1 for row in simulations if row.get("status") == "EXPIRED"),
            "partial_fills": sum(1 for row in simulations if 0 < float(row.get("fill_ratio") or 0) < 0.999),
            "unknown_incidents": sum(1 for row in simulations if row.get("incidents")),
            "execution_wired": False,
            "real_orders_submitted": 0,
        }
        if candidate_meta:
            summary["candidate_intake"] = candidate_meta
        payload = {
            "phase": 3,
            "mode": "execution_simulation_only",
            "status": (
                "HEALTHY"
                if candidates
                else (
                    "FILTERED_NO_EDGE"
                    if int((candidate_meta.get("raw_pool_size") or 0)) > 0
                    else "WAITING_FOR_SETTLED_FORECASTS"
                )
            ),
            "run": summary,
            "phase2_cycle": phase2_payload,
            "settlement": settlement,
            "policies": list(self.policies),
            "scenarios": list(self.scenarios),
            "simulations": simulations,
            "candidate_intake": candidate_meta,
            "execution_wired": False,
            "real_orders_submitted": 0,
        }
        payload["dataset_hash"] = hashlib.sha256(
            json.dumps({"run": summary, "simulations": simulations}, sort_keys=True, default=str).encode()
        ).hexdigest()
        self.data_store.persist_simulation_run(payload)
        with self._lock:
            self._latest = payload
            self._run_count += 1
        self._publish("buzz.execution_lab.snapshot", payload)
        self._publish("buzz.execution_lab.health", {
            "phase": 3,
            "status": payload["status"],
            "run_id": run_id,
            "simulations_created": len(simulations),
            "execution_wired": False,
            "real_orders_submitted": 0,
        })
        return payload
