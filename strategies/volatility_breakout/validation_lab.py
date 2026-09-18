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

    @staticmethod
    def _canonical_hash(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

    def _signature_for(self, payload: dict[str, Any]) -> str:
        body = {k: v for k, v in payload.items() if k not in {"signature", "payload"}}
        return self._canonical_hash(body)

    def _issue_phase4_verifier_ticket(self, run_id: str, candidate_result: dict[str, Any], now_ts: float, *, task_class: str = "phase4_candidate_replay_verification") -> dict[str, Any]:
        subject_digest = self._canonical_hash({
            "run_id": run_id,
            "candidate_key": candidate_result.get("candidate_key"),
            "robust_score": candidate_result.get("robust_score"),
            "normal": candidate_result.get("normal"),
            "recent": candidate_result.get("recent"),
        })
        payload = {
            "schema": "hivenance_commons_pool_work_ticket_v1",
            "ticket_id": self._canonical_hash({
                "type": "phase4_ticket",
                "run_id": run_id,
                "candidate_key": candidate_result.get("candidate_key"),
                "created_ts": float(now_ts),
            }),
            "pool_type": "verifier_pool",
            "task_class": str(task_class or "phase4_candidate_replay_verification"),
            "phase_scope": 4,
            "created_ts": float(now_ts),
            "expires_ts": float(now_ts + max(60, int(getattr(self.cfg, "phase4_commons_ticket_ttl_sec", 1800) or 1800))),
            "lease_count": 1,
            "authority": "verification_work_only",
            "world_state_digest": None,
            "input_root": subject_digest,
            "feature_schema_digest": self._canonical_hash({
                "candidate_key": candidate_result.get("candidate_key"),
                "model_id": candidate_result.get("model_id"),
                "order_policy": candidate_result.get("order_policy"),
            }),
            "code_digest": self._canonical_hash({
                "component": "validation_lab",
                "validator_version": self.validator.version,
            }),
            "config_digest": self._canonical_hash({
                "phase4_min_candidate_trades": getattr(self.cfg, "phase4_min_candidate_trades", None),
                "phase4_dsr_min_probability": getattr(self.cfg, "phase4_dsr_min_probability", None),
                "phase4_pbo_max": getattr(self.cfg, "phase4_pbo_max", None),
            }),
            "required_engine_profiles": ["python_cpu", "replay_verifier"],
            "required_verifiers": ["manifest", "policy", "schema"],
            "privacy_class": "public_market_validation",
            "challenge_nonce": self._canonical_hash({
                "run_id": run_id,
                "candidate_key": candidate_result.get("candidate_key"),
                "now_ts": float(now_ts),
            })[:24],
            "target_object": {
                "phase4_run_id": run_id,
                "candidate_key": candidate_result.get("candidate_key"),
                "model_id": candidate_result.get("model_id"),
                "order_policy": candidate_result.get("order_policy"),
            },
            "status": "ISSUED",
        }
        payload["signature"] = self._signature_for(payload)
        return payload

    def _verify_phase4_verifier_packet(
        self,
        packet: dict[str, Any],
        candidate_keys: set[str],
        now_ts: float,
        *,
        run_id: str,
    ) -> tuple[bool, list[str], str]:
        adoption = packet.get("adoption_receipt") if isinstance(packet.get("adoption_receipt"), dict) else {}
        verifier = packet.get("verifier_receipt") if isinstance(packet.get("verifier_receipt"), dict) else {}
        summary = verifier.get("verification_summary") if isinstance(verifier.get("verification_summary"), dict) else {}
        target = verifier.get("target_object") if isinstance(verifier.get("target_object"), dict) else {}
        reasons: list[str] = []
        if adoption.get("authority_ceiling") != "proposal_only":
            reasons.append("authority_ceiling_not_proposal_only")
        if adoption.get("local_reproduction_verdict") != "PASS":
            reasons.append("local_reproduction_not_passed")
        created_ts = float(verifier.get("created_ts") or 0.0)
        if created_ts <= 0 or (now_ts - created_ts) > float(max(60, int(getattr(self.cfg, "phase4_commons_max_packet_age_sec", 7200) or 7200))):
            reasons.append("packet_too_old")
        candidate_key = str(summary.get("candidate_key") or target.get("candidate_key") or "")
        if not candidate_key or candidate_key not in candidate_keys:
            reasons.append("candidate_not_in_local_validation_set")
        packet_run_id = str(target.get("phase4_run_id") or summary.get("phase4_run_id") or "")
        if packet_run_id != str(run_id):
            reasons.append("validation_run_mismatch")
        ticket_id = verifier.get("ticket_id")
        tickets = self.data_store.get_commons_pool_work_tickets(limit=200, pool_type="verifier_pool") if self.data_store is not None else []
        ticket = next((row for row in tickets if row.get("ticket_id") == ticket_id), None)
        if not ticket:
            reasons.append("ticket_not_found")
        else:
            if float(ticket.get("expires_ts") or 0.0) < now_ts:
                reasons.append("ticket_expired")
            if str(ticket.get("challenge_nonce") or "") != str(verifier.get("challenge_nonce") or ""):
                reasons.append("challenge_nonce_mismatch")
            if str(ticket.get("input_root") or "") != str(verifier.get("subject_digest") or ""):
                reasons.append("subject_digest_mismatch")
        signature = str(verifier.get("signature") or "")
        if not signature:
            reasons.append("signature_missing")
        elif signature != self._signature_for(verifier):
            reasons.append("signature_mismatch")
        verdict = str(verifier.get("verification_verdict") or "").upper()
        if verdict not in {"PASS", "FAIL", "CONTRADICT"}:
            reasons.append("unsupported_verification_verdict")
        return (not reasons, reasons, candidate_key)

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
        report["started_ts"] = started_ts
        candidate_results = report.get("candidate_results") if isinstance(report.get("candidate_results"), list) else []
        # Materialize the immutable verifier subjects before tickets become claimable.
        # The completed report overwrites this provisional row later in the same run.
        if not self.data_store.persist_phase4_validation_report(report):
            raise RuntimeError("failed to persist provisional Phase-4 verifier subjects")
        commons_tickets = []
        commons_ticket_store_available = hasattr(self.data_store, "persist_commons_pool_work_ticket")
        for candidate_result in candidate_results[: max(1, int(getattr(self.cfg, "phase4_commons_max_tickets_per_run", 12) or 12))] if commons_ticket_store_available else []:
            if not isinstance(candidate_result, dict):
                continue
            for task_class in (
                "phase4_candidate_replay_verification",
                "phase4_negative_case_replay",
                "phase4_walk_forward_reproduction",
                "phase4_pbo_confirmation",
            ):
                ticket = self._issue_phase4_verifier_ticket(run_id, candidate_result, started_ts, task_class=task_class)
                if self.data_store.persist_commons_pool_work_ticket(ticket):
                    commons_tickets.append(ticket)
        commons_packets_examined = 0
        commons_packets_accepted = 0
        commons_packets_rejected = 0
        commons_rejection_reasons: dict[str, int] = {}
        commons_by_candidate: dict[str, list[dict[str, Any]]] = {}
        packets = self.data_store.get_commons_phase4_adopted_verifier_packets(
            limit=200, run_id=run_id
        ) if hasattr(self.data_store, "get_commons_phase4_adopted_verifier_packets") else []
        candidate_keys = {str(item.get("candidate_key") or "") for item in candidate_results if isinstance(item, dict)}
        for packet in packets:
            commons_packets_examined += 1
            allowed, reasons, candidate_key = self._verify_phase4_verifier_packet(
                packet, candidate_keys, started_ts, run_id=run_id
            )
            if not allowed:
                commons_packets_rejected += 1
                for reason in reasons:
                    commons_rejection_reasons[reason] = commons_rejection_reasons.get(reason, 0) + 1
                continue
            commons_packets_accepted += 1
            commons_by_candidate.setdefault(candidate_key, []).append(packet)
        contradiction_count = 0
        contradiction_candidates = 0
        confirmation_count = 0
        for candidate_result in candidate_results:
            if not isinstance(candidate_result, dict):
                continue
            candidate_key = str(candidate_result.get("candidate_key") or "")
            packets_for_candidate = commons_by_candidate.get(candidate_key, [])
            verifier_annotations = []
            contradiction = False
            for packet in packets_for_candidate:
                verifier = packet.get("verifier_receipt") if isinstance(packet.get("verifier_receipt"), dict) else {}
                verdict = str(verifier.get("verification_verdict") or "").upper()
                summary = verifier.get("verification_summary") if isinstance(verifier.get("verification_summary"), dict) else {}
                verifier_annotations.append({
                    "receipt_id": verifier.get("receipt_id"),
                    "worker_id": verifier.get("worker_id"),
                    "task_class": verifier.get("task_class"),
                    "verification_verdict": verdict,
                    "verification_summary": summary,
                })
                if verdict in {"FAIL", "CONTRADICT"}:
                    contradiction = True
                    contradiction_count += 1
                elif verdict == "PASS":
                    confirmation_count += 1
            if verifier_annotations:
                candidate_result["commons_verifier"] = {
                    "receipts": verifier_annotations,
                    "contradiction_present": contradiction,
                }
            if contradiction:
                contradiction_candidates += 1
                reasons = candidate_result.get("reasons") if isinstance(candidate_result.get("reasons"), list) else []
                if "commons_verifier_contradiction" not in reasons:
                    reasons.append("commons_verifier_contradiction")
                candidate_result["reasons"] = reasons
                candidate_result["ready_for_phase5_review"] = False
        completed_ts = time.time()
        report["completed_ts"] = completed_ts
        report["phase3_cycle"] = phase3_payload
        readiness = report.get("readiness") if isinstance(report.get("readiness"), dict) else {}
        reasons = list(readiness.get("reasons") or [])
        if contradiction_candidates and "commons_verifier_contradiction_present" not in reasons:
            reasons.append("commons_verifier_contradiction_present")
        if readiness:
            readiness["reasons"] = reasons
            readiness["ready_for_phase5_review"] = bool(readiness.get("ready_for_phase5_review")) and not contradiction_candidates
        report["readiness"] = readiness
        report["commons_verifier_pool"] = {
            "tickets_issued": len(commons_tickets),
            "adopted_packets_examined": commons_packets_examined,
            "adopted_packets_accepted": commons_packets_accepted,
            "adopted_packets_rejected": commons_packets_rejected,
            "rejection_reasons": commons_rejection_reasons,
            "contradiction_receipts": contradiction_count,
            "contradiction_candidates": contradiction_candidates,
            "confirmation_receipts": confirmation_count,
            "authority": "proposal_only",
            "promotion_authority": "none",
        }
        report["dataset_hash"] = hashlib.sha256(
            json.dumps({
                "validator_version": self.validator.version,
                "rows": rows,
                "candidate_results": report.get("candidate_results"),
                "commons_verifier_pool": report.get("commons_verifier_pool"),
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
