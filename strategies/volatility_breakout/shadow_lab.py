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

    @staticmethod
    def _canonical_hash(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

    def _signature_for(self, payload: dict[str, Any]) -> str:
        body = {k: v for k, v in payload.items() if k not in {"signature", "payload"}}
        return self._canonical_hash(body)

    def _issue_phase5_verifier_ticket(self, freeze_record: dict[str, Any], readiness: dict[str, Any], now_ts: float, *, task_class: str = "phase5_shadow_integrity_verification") -> dict[str, Any]:
        subject_digest = self._canonical_hash({
            "freeze_id": freeze_record.get("freeze_id"),
            "phase4_run_id": freeze_record.get("phase4_run_id"),
            "candidate_key": freeze_record.get("candidate_key"),
            "config_hash": freeze_record.get("config_hash"),
            "readiness": readiness,
        })
        payload = {
            "schema": "hivenance_commons_pool_work_ticket_v1",
            "ticket_id": self._canonical_hash({
                "type": "phase5_ticket",
                "freeze_id": freeze_record.get("freeze_id"),
                "created_ts": float(now_ts),
            }),
            "pool_type": "verifier_pool",
            "task_class": str(task_class or "phase5_shadow_integrity_verification"),
            "phase_scope": 5,
            "created_ts": float(now_ts),
            "expires_ts": float(now_ts + max(60, int(getattr(self.cfg, "phase5_commons_ticket_ttl_sec", 1800) or 1800))),
            "lease_count": 1,
            "authority": "verification_work_only",
            "world_state_digest": None,
            "input_root": subject_digest,
            "feature_schema_digest": self._canonical_hash({
                "candidate_key": freeze_record.get("candidate_key"),
                "model_id": freeze_record.get("model_id"),
                "order_policy": freeze_record.get("order_policy"),
            }),
            "code_digest": self._canonical_hash({
                "component": "shadow_flight",
                "settler": "phase5_shadow_settlement_engine",
            }),
            "config_digest": self._canonical_hash({
                "phase5_readiness_min_settled": getattr(self.cfg, "phase5_readiness_min_settled", None),
                "phase5_readiness_min_fill_ratio": getattr(self.cfg, "phase5_readiness_min_fill_ratio", None),
                "phase5_readiness_require_positive_mean": getattr(self.cfg, "phase5_readiness_require_positive_mean", None),
            }),
            "required_engine_profiles": ["python_cpu", "shadow_verifier"],
            "required_verifiers": ["manifest", "policy", "schema"],
            "privacy_class": "public_shadow_validation",
            "challenge_nonce": self._canonical_hash({
                "freeze_id": freeze_record.get("freeze_id"),
                "now_ts": float(now_ts),
            })[:24],
            "target_object": {
                "freeze_id": freeze_record.get("freeze_id"),
                "phase4_run_id": freeze_record.get("phase4_run_id"),
                "candidate_key": freeze_record.get("candidate_key"),
                "model_id": freeze_record.get("model_id"),
            },
            "status": "ISSUED",
        }
        payload["signature"] = self._signature_for(payload)
        return payload

    def _verify_phase5_verifier_packet(self, packet: dict[str, Any], freeze_ids: set[str], now_ts: float) -> tuple[bool, list[str], str]:
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
        if created_ts <= 0 or (now_ts - created_ts) > float(max(60, int(getattr(self.cfg, "phase5_commons_max_packet_age_sec", 7200) or 7200))):
            reasons.append("packet_too_old")
        freeze_id = str(summary.get("freeze_id") or target.get("freeze_id") or "")
        if not freeze_id or freeze_id not in freeze_ids:
            reasons.append("freeze_not_in_local_shadow_set")
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
        summary_reasons = {str(item) for item in (summary.get("reasons") or [])}
        if summary.get("digest_matches") is False or "subject_digest_reconstruction_mismatch" in summary_reasons:
            reasons.append("verifier_subject_digest_reconstruction_mismatch")
        return (not reasons, reasons, freeze_id)

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
            symbol=str(record.get("symbol") or "") or None,
            direction=str(record.get("direction") or "").upper() or None,
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
                        # Phase 5 only needs fresh post-approval forecasts for the frozen
                        # champion slice. Recomputing the full historical Phase-2 scorecard
                        # here turns shadow flight into a large database scan and does not
                        # change the freeze authority.
                        "phase2_cycle": hypothesis_swarm.run_once(scorecard_context={
                            "profitability_frontier": [],
                            "regime_model_breakdown": [],
                        }),
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
                    symbol=freeze.symbol,
                    direction=freeze.direction,
                    approved_after_ts=freeze.approved_ts,
                    limit=self.max_intents,
                    now_ts=started_ts,
                )
                if len(candidates) < self.max_intents and hasattr(self.data_store, "get_phase5_frozen_shadow_admission_candidates"):
                    existing_forecast_ids = {str(candidate.get("forecast_id") or "") for candidate in candidates}
                    path_a_candidates = self.data_store.get_phase5_frozen_shadow_admission_candidates(
                        model_id=freeze.model_id,
                        symbol=freeze.symbol,
                        direction=freeze.direction,
                        approved_after_ts=freeze.approved_ts,
                        limit=self.max_intents - len(candidates),
                        now_ts=started_ts,
                        min_utility=float(getattr(self.cfg, "phase5_frozen_shadow_min_utility", 0.30) or 0.30),
                    )
                    for candidate in path_a_candidates:
                        if str(candidate.get("forecast_id") or "") not in existing_forecast_ids:
                            candidates.append(candidate)
                            existing_forecast_ids.add(str(candidate.get("forecast_id") or ""))
                if (
                    freeze.model_id == "small_window_trend_comparison_v1"
                    and len(candidates) < self.max_intents
                    and hasattr(self.data_store, "get_phase5_small_window_shadow_candidates")
                ):
                    existing_forecast_ids = {str(candidate.get("forecast_id") or "") for candidate in candidates}
                    small_window_candidates = self.data_store.get_phase5_small_window_shadow_candidates(
                        model_id=freeze.model_id,
                        symbol=freeze.symbol,
                        direction=freeze.direction,
                        approved_after_ts=freeze.approved_ts,
                        limit=self.max_intents - len(candidates),
                        now_ts=started_ts,
                    )
                    for candidate in small_window_candidates:
                        if str(candidate.get("forecast_id") or "") not in existing_forecast_ids:
                            candidates.append(candidate)
                            existing_forecast_ids.add(str(candidate.get("forecast_id") or ""))
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
            distinct_bucket_hours=int(getattr(self.cfg, "phase5_readiness_distinct_snapshot_bucket_hours", 24) or 24),
        )
        commons_tickets = []
        if freeze_record:
            for task_class in (
                "phase5_shadow_integrity_verification",
                "phase5_frozen_config_replay",
                "phase5_shadow_settlement_audit",
                "phase5_drift_confirmation",
            ):
                ticket = self._issue_phase5_verifier_ticket(freeze_record, readiness, started_ts, task_class=task_class)
                if self.data_store.persist_commons_pool_work_ticket(ticket):
                    commons_tickets.append(ticket)
        commons_packets_examined = 0
        commons_packets_accepted = 0
        commons_packets_rejected = 0
        commons_rejection_reasons: dict[str, int] = {}
        contradiction_receipts = 0
        confirmation_receipts = 0
        verifier_annotations = []
        packets = self.data_store.get_commons_phase5_adopted_verifier_packets(limit=200) if hasattr(self.data_store, "get_commons_phase5_adopted_verifier_packets") else []
        freeze_ids = {str((freeze_record or {}).get("freeze_id") or "")} if freeze_record else set()
        for packet in packets:
            commons_packets_examined += 1
            allowed, packet_reasons, freeze_id = self._verify_phase5_verifier_packet(packet, freeze_ids, started_ts)
            if not allowed:
                commons_packets_rejected += 1
                for reason in packet_reasons:
                    commons_rejection_reasons[reason] = commons_rejection_reasons.get(reason, 0) + 1
                continue
            commons_packets_accepted += 1
            verifier = packet.get("verifier_receipt") if isinstance(packet.get("verifier_receipt"), dict) else {}
            verdict = str(verifier.get("verification_verdict") or "").upper()
            verifier_annotations.append({
                "receipt_id": verifier.get("receipt_id"),
                "worker_id": verifier.get("worker_id"),
                "task_class": verifier.get("task_class"),
                "verification_verdict": verdict,
                "verification_summary": verifier.get("verification_summary") if isinstance(verifier.get("verification_summary"), dict) else {},
            })
            if verdict in {"FAIL", "CONTRADICT"}:
                contradiction_receipts += 1
            elif verdict == "PASS":
                confirmation_receipts += 1
        readiness_reasons = list(readiness.get("reasons") or [])
        if contradiction_receipts and "commons_shadow_verifier_contradiction_present" not in readiness_reasons:
            readiness_reasons.append("commons_shadow_verifier_contradiction_present")
        readiness["reasons"] = readiness_reasons
        readiness["ready_for_phase6_review"] = bool(readiness.get("ready_for_phase6_review")) and not contradiction_receipts
        readiness["commons_verifier_pool"] = {
            "tickets_issued": len(commons_tickets),
            "adopted_packets_examined": commons_packets_examined,
            "adopted_packets_accepted": commons_packets_accepted,
            "adopted_packets_rejected": commons_packets_rejected,
            "rejection_reasons": commons_rejection_reasons,
            "contradiction_receipts": contradiction_receipts,
            "confirmation_receipts": confirmation_receipts,
            "receipts": verifier_annotations,
            "authority": "proposal_only",
            "phase6_review_authority": "none",
        }
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
            "commons_verifier_pool": readiness.get("commons_verifier_pool") or {},
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
                "commons_verifier_pool": payload.get("commons_verifier_pool"),
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
