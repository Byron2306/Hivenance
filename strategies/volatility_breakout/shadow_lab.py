from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Optional

from .shadow_flight import ShadowIntentBuilder, ShadowSettlementEngine, frozen_config_hash
from .shadow_models import ShadowFreeze


class ShadowFlightAgent:
    """Phase-5 live-public-data shadow runner with no transmission capability."""

    def __init__(
        self,
        cfg: Any,
        validation_lab: Any,
        data_store: Any,
        coordinator: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg
        self.validation_lab = validation_lab
        self.data_store = data_store
        self.coordinator = coordinator
        self.enabled = bool(getattr(cfg, "phase5_shadow_enabled", True))
        self.interval_sec = max(30, int(getattr(cfg, "phase5_interval_sec", 120) or 120))
        self.max_intents = max(1, int(getattr(cfg, "phase5_shadow_max_intents_per_cycle", 25) or 25))
        self.builder = ShadowIntentBuilder(cfg)
        self.settler = ShadowSettlementEngine(cfg)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._run_count = 0
        self._last_error: Optional[str] = None
        self._latest: dict[str, Any] = {
            "phase": 5,
            "mode": "public_shadow_only",
            "status": "INITIALIZED" if self.enabled else "DISABLED",
            "execution_wired": False,
            "private_exchange_access": False,
            "real_orders_submitted": 0,
            "transmission_attempts": 0,
        }

    def start(self) -> bool:
        if not self.enabled or self.data_store is None:
            with self._lock:
                self._latest["status"] = "UNAVAILABLE"
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hivenance-shadow-flight", daemon=True)
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
            "phase": 5,
            "mode": "public_shadow_only",
            "enabled": self.enabled,
            "status": status,
            "run_count": self._run_count,
            "last_error": self._last_error,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "execution_wired": False,
            "private_exchange_access": False,
            "real_orders_submitted": 0,
            "transmission_attempts": 0,
        }

    def latest_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._latest, default=str))

    def _publish(self, key: str, payload: dict[str, Any]) -> None:
        if self.coordinator and hasattr(self.coordinator, "share_data"):
            self.coordinator.share_data(key, {
                "buzz": {"type": key, "source": "SHADOW_FLIGHT", "ts": int(time.time() * 1000)},
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
                logging.exception("Shadow flight cycle failed")
                with self._lock:
                    self._latest["status"] = "ERROR"
            self._stop.wait(max(1.0, self.interval_sec - (time.monotonic() - started)))

    @staticmethod
    def _freeze_from_record(record: dict[str, Any]) -> ShadowFreeze:
        return ShadowFreeze(
            freeze_id=str(record.get("freeze_id") or ""),
            phase4_run_id=str(record.get("phase4_run_id") or ""),
            candidate_key=str(record.get("candidate_key") or ""),
            model_id=str(record.get("model_id") or ""),
            order_policy=str(record.get("order_policy") or ""),
            approved_by=str(record.get("approved_by") or ""),
            approved_ts=float(record.get("approved_ts") or 0.0),
            phase4_dataset_hash=str(record.get("phase4_dataset_hash") or ""),
            config_hash=str(record.get("config_hash") or ""),
            status=str(record.get("status") or "ACTIVE"),
        )

    def run_once(self, *, drive_upstream: bool = True) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("phase5 shadow flight is disabled")
        started_ts = time.time()
        run_id = f"shadow-{int(started_ts * 1000)}-{uuid.uuid4().hex[:8]}"
        upstream_payload = None
        preexisting_freeze = self.data_store.get_phase5_active_freeze()
        current_hash = frozen_config_hash(self.cfg)
        if drive_upstream and self.validation_lab is not None:
            if preexisting_freeze:
                # Once a champion is approved, its Phase-4 court record is frozen.
                # Continue only the public observer/hypothesis path so fresh forecasts
                # arrive without silently replacing the approved validation run.
                if str(preexisting_freeze.get("config_hash") or "") == current_hash:
                    execution_lab = getattr(self.validation_lab, "execution_lab", None)
                    hypothesis_swarm = getattr(execution_lab, "hypothesis_swarm", None)
                    if hypothesis_swarm is None or not hasattr(hypothesis_swarm, "run_once"):
                        raise RuntimeError("frozen Phase-5 upstream hypothesis path is unavailable")
                    upstream_payload = {
                        "mode": "frozen_champion_public_hypothesis_only",
                        "phase2_cycle": hypothesis_swarm.run_once(),
                    }
            else:
                # Before approval, keep accumulating the complete Phase-4 evidence chain.
                upstream_payload = self.validation_lab.run_once(drive_phase3=True)

        settlement = self.data_store.settle_mature_shadow_intents(
            self.settler,
            now_ts=time.time(),
            tolerance_sec=int(getattr(self.cfg, "phase5_shadow_settlement_tolerance_sec", 900) or 900),
        )
        freeze_record = self.data_store.get_phase5_active_freeze()
        status = "LOCKED_AWAITING_HUMAN_APPROVAL"
        reasons: list[str] = []
        intents_created = 0
        skipped = 0
        if not freeze_record:
            reasons.append("no_active_human_approved_freeze")
        else:
            freeze = self._freeze_from_record(freeze_record)
            latest_phase4 = self.data_store.get_phase4_latest_report()
            readiness = latest_phase4.get("readiness") or {}
            champion = latest_phase4.get("champion") or {}
            if freeze.status != "ACTIVE":
                reasons.append("freeze_not_active")
            if freeze.config_hash != current_hash:
                reasons.append("frozen_parameter_drift")
            if not readiness.get("ready_for_phase5_review"):
                reasons.append("phase4_readiness_revoked")
            if str(latest_phase4.get("run_id") or "") != freeze.phase4_run_id:
                reasons.append("phase4_run_changed_after_approval")
            if str(champion.get("candidate_key") or "") != freeze.candidate_key:
                reasons.append("phase4_champion_changed_after_approval")
            if reasons:
                status = "LOCKED"
            else:
                status = "SHADOW_ACTIVE"
                candidates = self.data_store.get_phase5_forecast_candidates(
                    model_id=freeze.model_id,
                    approved_after_ts=freeze.approved_ts,
                    limit=self.max_intents,
                    now_ts=started_ts,
                )
                for candidate in candidates:
                    try:
                        intent = self.builder.build(candidate, candidate.get("entry_observation") or {}, freeze)
                        if self.data_store.persist_shadow_intent(intent.to_dict()):
                            intents_created += 1
                        else:
                            skipped += 1
                    except ValueError:
                        skipped += 1
        readiness = self.data_store.get_phase5_readiness(
            min_distinct_days=int(getattr(self.cfg, "phase5_readiness_min_distinct_days", 30) or 30),
            min_settled=int(getattr(self.cfg, "phase5_readiness_min_settled", 100) or 100),
            max_cost_mae_bps=float(getattr(self.cfg, "phase5_readiness_max_cost_mae_bps", 20.0) or 20.0),
            min_fill_ratio=float(getattr(self.cfg, "phase5_readiness_min_fill_ratio", 0.50) or 0.50),
            require_positive_mean=bool(getattr(self.cfg, "phase5_readiness_require_positive_mean", True)),
            current_config_hash=current_hash,
        )
        completed_ts = time.time()
        payload = {
            "phase": 5,
            "mode": "public_shadow_only",
            "status": status,
            "run_id": run_id,
            "started_ts": started_ts,
            "completed_ts": completed_ts,
            "upstream_cycle": upstream_payload,
            "freeze": freeze_record or {},
            "frozen_config_hash": (freeze_record or {}).get("config_hash"),
            "current_config_hash": current_hash,
            "intents_created": intents_created,
            "intents_skipped": skipped,
            "settlement": settlement,
            "readiness": readiness,
            "reasons": reasons,
            "execution_wired": False,
            "private_exchange_access": False,
            "credentials_used": False,
            "transmission_attempts": 0,
            "real_orders_submitted": 0,
            "live_eligible": False,
        }
        payload["dataset_hash"] = hashlib.sha256(
            json.dumps({
                "freeze": payload["freeze"],
                "intents_created": intents_created,
                "settlement": settlement,
                "readiness": readiness,
            }, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        self.data_store.persist_phase5_shadow_run(payload)
        with self._lock:
            self._latest = payload
            self._run_count += 1
        self._publish("buzz.shadow_flight.snapshot", payload)
        self._publish("buzz.shadow_flight.health", {
            "phase": 5,
            "status": status,
            "run_id": run_id,
            "intents_created": intents_created,
            "settled": settlement.get("settled", 0),
            "ready_for_phase6_review": bool(readiness.get("ready_for_phase6_review")),
            "execution_wired": False,
            "real_orders_submitted": 0,
        })
        return payload
