from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agents.commons_authority import validate_artifact_contract
from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition
from strategies.volatility_breakout.hypothesis_swarm import CommonsPhase2Governor, _feature_from_payload


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _signed_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    payload["signature"] = _canonical_hash(
        {key: value for key, value in payload.items() if key not in {"signature", "payload"}}
    )
    return payload


class SovereignPoolWorker:
    """Local proposal/verifier worker with no execution or promotion authority."""

    worker_id = "hivenance_sovereign_pool_local_v1"

    def __init__(
        self,
        cfg: Any,
        data_store: DataStoreAgent,
        *,
        database: Path,
        ollama_url: str = "http://127.0.0.1:11434",
        ollama_model: str = "beast-crystal-qwen25-05b:latest",
    ) -> None:
        self.cfg = cfg
        self.data_store = data_store
        self.database = Path(database)
        self.ollama_url = ollama_url.rstrip("/")
        self.ollama_model = ollama_model
        self.competition = HypothesisCompetition(cfg)
        self.phase2_governor = CommonsPhase2Governor(cfg, data_store)
        self._invalid_adoptions_reconciled = False

    def process_once(self, *, limit: int = 100) -> dict[str, Any]:
        now_ts = time.time()
        revoked = 0
        if not self._invalid_adoptions_reconciled:
            revoked = self._revoke_invalid_inference_adoptions()
            self._invalid_adoptions_reconciled = True
        tickets_issued = self._issue_fresh_phase2_tickets(now_ts) + self._issue_phase4_verifier_tickets(now_ts)
        tickets = self.data_store.get_commons_pool_work_tickets(limit=max(1, int(limit)))
        inference_done = {
            str(row.get("ticket_id") or "")
            for row in self.data_store.get_commons_inference_receipts(limit=max(250, int(limit) * 4))
        }
        verifier_done = {
            str(row.get("ticket_id") or "")
            for row in self.data_store.get_commons_verifier_receipts(limit=max(250, int(limit) * 4))
        }
        summary: dict[str, Any] = {
            "worker_id": self.worker_id,
            "authority": "proposal_and_verification_only",
            "execution_authority": "none",
            "examined": len(tickets),
            "tickets_issued": tickets_issued,
            "invalid_adoptions_revoked": revoked,
            "claimable": 0,
            "expired": 0,
            "inference_receipts": 0,
            "verifier_receipts": 0,
            "rejected": 0,
            "errors": [],
        }
        for row in reversed(tickets):
            ticket = self._ticket_payload(row)
            if not ticket:
                summary["rejected"] += 1
                continue
            if float(ticket.get("expires_ts") or 0.0) <= now_ts:
                summary["expired"] += 1
                continue
            ticket_id = str(ticket.get("ticket_id") or "")
            pool_type = str(ticket.get("pool_type") or "")
            if (pool_type == "inference_pool" and ticket_id in inference_done) or (
                pool_type == "verifier_pool" and ticket_id in verifier_done
            ):
                continue
            contract = validate_artifact_contract(
                ticket,
                expected_schema="hivenance_commons_pool_work_ticket_v1",
                requested_authority="proposal_only",
            )
            if not contract.get("ok"):
                summary["rejected"] += 1
                summary["errors"].append({"ticket_id": ticket_id, "reasons": contract.get("reasons") or []})
                continue
            summary["claimable"] += 1
            try:
                lease = self._lease(ticket, now_ts)
                if not self.data_store.persist_commons_pool_claim_lease(lease):
                    raise RuntimeError("lease_persistence_failed")
                if pool_type == "inference_pool":
                    receipt = self._inference_receipt(ticket, lease, now_ts)
                    if not self.data_store.ingest_commons_inference_packet(
                        receipt,
                        adopted_by=self.worker_id,
                        adoption_decision="ACCEPTED_CHALLENGER_FORECAST",
                        authority_ceiling="proposal_only",
                        reasons=["locally_reproduced_from_ticket_bound_feature_vector"],
                        adoption_payload={"worker_stack": receipt.get("worker_stack")},
                    ):
                        raise RuntimeError("inference_ingest_failed")
                    summary["inference_receipts"] += 1
                elif pool_type == "verifier_pool":
                    receipt = self._verifier_receipt(ticket, lease, now_ts)
                    decision = (
                        "ACCEPTED_CONTRADICTION_EVIDENCE"
                        if str(receipt.get("verification_verdict") or "").upper() in {"FAIL", "CONTRADICT"}
                        else "ACCEPTED_VALIDATION_EVIDENCE"
                    )
                    if int(ticket.get("phase_scope") or 0) == 5:
                        decision = (
                            "ACCEPTED_SHADOW_CONTRADICTION"
                            if str(receipt.get("verification_verdict") or "").upper() in {"FAIL", "CONTRADICT"}
                            else "ACCEPTED_SHADOW_EVIDENCE"
                        )
                    if not self.data_store.ingest_commons_verifier_packet(
                        receipt,
                        adopted_by=self.worker_id,
                        adoption_decision=decision,
                        authority_ceiling="proposal_only",
                        reasons=["independent_local_evidence_reconstruction"],
                        adoption_payload={"worker_stack": receipt.get("worker_stack")},
                    ):
                        raise RuntimeError("verifier_ingest_failed")
                    summary["verifier_receipts"] += 1
                else:
                    summary["rejected"] += 1
            except Exception as exc:
                summary["errors"].append({"ticket_id": ticket_id, "error": f"{type(exc).__name__}:{exc}"})
        summary["status"] = "ONLINE" if not summary["errors"] else "DEGRADED"
        summary["completed_ts"] = time.time()
        return summary

    def _revoke_invalid_inference_adoptions(self) -> int:
        revoked = 0
        baseline_ids = set(self.competition.baseline_ids)
        quarantined_ids = set(self.competition.federation.quarantined_models)
        for row in self.data_store.get_commons_inference_receipts(limit=5000):
            raw = row.get("payload")
            try:
                receipt = json.loads(raw or "{}") if isinstance(raw, str) else dict(raw or {})
            except (TypeError, json.JSONDecodeError):
                continue
            summary = receipt.get("result_summary") if isinstance(receipt.get("result_summary"), dict) else {}
            model_id = str(summary.get("model_id") or "")
            selected_model = model_id.split("::", 1)[-1]
            if selected_model not in baseline_ids and selected_model not in quarantined_ids:
                continue
            reason = (
                "quarantined_model_cannot_be_adopted_as_commons_challenger"
                if selected_model in quarantined_ids
                else "baseline_model_cannot_be_adopted_as_commons_challenger"
            )
            if self.data_store.revoke_commons_local_adoption(
                str(receipt.get("receipt_id") or ""),
                reason=reason,
            ):
                revoked += 1
        return revoked

    def _issue_fresh_phase2_tickets(self, now_ts: float) -> int:
        """Issue one reproducible batch when Phase 2 is delayed by scorecard I/O."""
        freshness_limit = max(30.0, float(getattr(self.cfg, "commons_worker_observation_max_age_sec", 120.0) or 120.0))
        with sqlite3.connect(str(self.database), timeout=30.0) as conn:
            run = conn.execute(
                """
                SELECT run_id, completed_ts, venue
                FROM observation_runs
                WHERE completed_ts IS NOT NULL
                ORDER BY completed_ts DESC
                LIMIT 1
                """
            ).fetchone()
            if not run or now_ts - float(run[1] or 0.0) > freshness_limit:
                return 0
            rows = conn.execute(
                """
                SELECT payload
                FROM observation_snapshots
                WHERE run_id=? AND observation_eligible=1
                ORDER BY data_quality DESC, quote_volume_24h DESC
                LIMIT ?
                """,
                (str(run[0]), int(self.phase2_governor.max_tickets_per_run)),
            ).fetchall()
        existing = self.data_store.get_commons_pool_work_tickets(limit=500, pool_type="inference_pool")
        for row in existing:
            payload = self._ticket_payload(row)
            target = payload.get("target_object") if isinstance(payload.get("target_object"), dict) else {}
            if str(target.get("phase2_observation_id") or "") == str(run[0]) and payload.get("input_payload"):
                return 0
        candidates: list[tuple[dict[str, Any], Any]] = []
        for (raw_payload,) in rows:
            try:
                candidate = json.loads(raw_payload or "{}")
            except json.JSONDecodeError:
                continue
            values = candidate.get("values") if isinstance(candidate.get("values"), dict) else {}
            feature = _feature_from_payload(values.get("feature_vector") or {})
            if feature is not None:
                candidates.append((candidate, feature))
        if not candidates:
            return 0
        issued = self.phase2_governor.issue_tickets(
            observation_run_id=str(run[0]),
            venue=str(run[2] or getattr(self.cfg, "exchange", "kraken")),
            candidates=candidates,
            horizons=(int((getattr(self.cfg, "phase2_horizons_seconds", [300]) or [300])[0]),),
            created_ts=now_ts,
        )
        return len(issued)

    def _issue_phase4_verifier_tickets(self, now_ts: float) -> int:
        with sqlite3.connect(str(self.database), timeout=30.0) as conn:
            run = conn.execute(
                "SELECT run_id FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT 1"
            ).fetchone()
            if not run:
                return 0
            rows = conn.execute(
                """
                SELECT payload
                FROM phase4_candidate_results
                WHERE run_id=?
                ORDER BY robust_score DESC
                LIMIT 12
                """,
                (str(run[0]),),
            ).fetchall()
        existing = self.data_store.get_commons_pool_work_tickets(limit=500, pool_type="verifier_pool")
        for row in existing:
            payload = self._ticket_payload(row)
            target = payload.get("target_object") if isinstance(payload.get("target_object"), dict) else {}
            if (
                str(target.get("phase4_run_id") or "") == str(run[0])
                and str(payload.get("issuer_worker_id") or "") == self.worker_id
            ):
                return 0
        issued = 0
        for (raw_payload,) in rows:
            try:
                candidate = json.loads(raw_payload or "{}")
            except json.JSONDecodeError:
                continue
            subject_digest = _canonical_hash({
                "run_id": str(run[0]),
                "candidate_key": candidate.get("candidate_key"),
                "robust_score": candidate.get("robust_score"),
                "normal": candidate.get("normal"),
                "recent": candidate.get("recent"),
            })
            ticket = {
                "schema": "hivenance_commons_pool_work_ticket_v1",
                "ticket_id": _canonical_hash({
                    "type": "phase4_sovereign_verifier_ticket",
                    "run_id": str(run[0]),
                    "candidate_key": candidate.get("candidate_key"),
                    "created_ts": now_ts,
                }),
                "pool_type": "verifier_pool",
                "task_class": "phase4_candidate_replay_verification",
                "phase_scope": 4,
                "created_ts": now_ts,
                "expires_ts": now_ts + 1800.0,
                "lease_count": 1,
                "authority": "verification_work_only",
                "world_state_digest": None,
                "input_root": subject_digest,
                "feature_schema_digest": _canonical_hash({
                    "candidate_key": candidate.get("candidate_key"),
                    "model_id": candidate.get("model_id"),
                    "order_policy": candidate.get("order_policy"),
                }),
                "code_digest": _canonical_hash({"component": "sovereign_pool_phase4_replay", "version": 1}),
                "config_digest": _canonical_hash({"source_run": str(run[0])}),
                "required_engine_profiles": ["python_cpu", "replay_verifier"],
                "required_verifiers": ["manifest", "policy", "schema", "subject_digest"],
                "privacy_class": "public_market_validation",
                "challenge_nonce": _canonical_hash({
                    "run_id": str(run[0]),
                    "candidate_key": candidate.get("candidate_key"),
                    "created_ts": now_ts,
                })[:24],
                "target_object": {
                    "phase4_run_id": str(run[0]),
                    "candidate_key": candidate.get("candidate_key"),
                    "model_id": candidate.get("model_id"),
                    "order_policy": candidate.get("order_policy"),
                },
                "issuer_worker_id": self.worker_id,
                "status": "ISSUED",
            }
            ticket = _signed_receipt(ticket)
            if self.data_store.persist_commons_pool_work_ticket(ticket):
                issued += 1
        return issued

    @staticmethod
    def _ticket_payload(row: dict[str, Any]) -> dict[str, Any]:
        raw = row.get("payload")
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}
        return dict(raw) if isinstance(raw, dict) else dict(row)

    def _lease(self, ticket: dict[str, Any], now_ts: float) -> dict[str, Any]:
        body = {
            "ticket_id": ticket.get("ticket_id"),
            "worker_id": self.worker_id,
            "issued_ts": now_ts,
            "expires_ts": min(float(ticket.get("expires_ts") or now_ts), now_ts + 300.0),
            "worker_advertisement_digest": _canonical_hash(self._worker_stack()),
            "challenge_nonce": ticket.get("challenge_nonce"),
            "authority": "proposal_only" if ticket.get("pool_type") == "inference_pool" else "verify_only",
            "max_result_bytes": 262_144,
            "status": "ACTIVE",
        }
        return {
            "schema": "hivenance_commons_claim_lease_v1",
            "lease_id": _canonical_hash(body),
            **body,
        }

    def _observation_feature(self, ticket: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        target = ticket.get("target_object") if isinstance(ticket.get("target_object"), dict) else {}
        input_payload = ticket.get("input_payload") if isinstance(ticket.get("input_payload"), dict) else {}
        feature = _feature_from_payload(input_payload.get("feature_vector") or {})
        with sqlite3.connect(str(self.database), timeout=30.0) as conn:
            row = conn.execute(
                "SELECT payload FROM observation_snapshots WHERE run_id=? AND symbol=? LIMIT 1",
                (str(target.get("phase2_observation_id") or ""), str(target.get("symbol") or "")),
            ).fetchone()
        if not row:
            raise ValueError("ticket_bound_observation_not_found")
        observation = json.loads(row[0] or "{}")
        if feature is None:
            raise ValueError("ticket_bound_feature_payload_missing")
        if _canonical_hash(asdict(feature)) != str(ticket.get("feature_schema_digest") or ""):
            raise ValueError("feature_schema_digest_mismatch")
        return feature, observation

    def _inference_receipt(self, ticket: dict[str, Any], lease: dict[str, Any], now_ts: float) -> dict[str, Any]:
        feature, observation = self._observation_feature(ticket)
        target = ticket.get("target_object") if isinstance(ticket.get("target_object"), dict) else {}
        horizon = int(target.get("horizon_seconds") or 300)
        forecasts = self.competition.evaluate(feature, (horizon,))
        baseline_ids = set(self.competition.baseline_ids)
        eligible = [
            row for row in forecasts
            if not row.abstain and not row.execution_eligible and row.model_id not in baseline_ids
        ]
        selected = max(
            eligible,
            key=lambda row: (float(row.expected_net_bps or -1e12), float(row.probability_positive_net or 0.0)),
            default=None,
        )
        candidates = [
            {
                "model_id": row.model_id,
                "direction": row.direction,
                "abstain": bool(row.abstain),
                "expected_net_bps": row.expected_net_bps,
                "probability_positive_net": row.probability_positive_net,
                "reason": row.reason,
            }
            for row in forecasts
            if row.model_id not in baseline_ids
        ]
        beast_review = self._beast_review(feature.symbol, target.get("regime_hint"), candidates, selected)
        force_abstain = bool(beast_review.get("veto"))
        if selected is None or force_abstain:
            result_summary = {
                "symbol": feature.symbol,
                "venue": observation.get("venue") or target.get("venue"),
                "horizon_seconds": horizon,
                "model_id": "beast_crystal_governed_ensemble_v1",
                "hypothesis": "governed_federated_challenger",
                "direction": "ABSTAIN",
                "entry_price": feature.price,
                "probability_positive_net": 0.0,
                "expected_move_bps": 0.0,
                "expected_cost_bps": None,
                "expected_net_bps": None,
                "raw_score": 0.0,
                "uncertainty": 1.0,
                "reason": "beast_reviewer_veto" if force_abstain else "no_local_federated_model_cleared_cost_gates",
                "reasons": beast_review.get("risks") or [],
                "feature_version": "sovereign_pool.v1",
                "inputs": {"candidate_manifest": candidates, "beast_review": beast_review},
            }
        else:
            result_summary = {
                **asdict(selected),
                "model_id": f"beast_crystal_selected::{selected.model_id}",
                "hypothesis": f"governed_challenger::{selected.hypothesis}",
                "entry_price": feature.price,
                "inputs": {
                    **dict(selected.inputs or {}),
                    "candidate_manifest": candidates,
                    "beast_review": beast_review,
                },
            }
        output_root = _canonical_hash(result_summary)
        receipt = {
            "schema": "hivenance_inference_pool_result_receipt_v1",
            "receipt_type": "inference",
            "receipt_id": _canonical_hash({"ticket": ticket.get("ticket_id"), "worker": self.worker_id, "output": output_root}),
            "ticket_id": ticket.get("ticket_id"),
            "lease_id": lease.get("lease_id"),
            "worker_id": self.worker_id,
            "created_ts": now_ts,
            "expires_ts": lease.get("expires_ts"),
            "pool_type": "inference_pool",
            "task_class": ticket.get("task_class"),
            "phase_scope": int(ticket.get("phase_scope") or 0),
            "challenge_nonce": ticket.get("challenge_nonce"),
            "input_root": ticket.get("input_root"),
            "output_root": output_root,
            "world_state_digest": ticket.get("world_state_digest"),
            "feature_schema_digest": ticket.get("feature_schema_digest"),
            "code_digest": ticket.get("code_digest"),
            "config_digest": ticket.get("config_digest"),
            "container_digest": None,
            "result_kind": "challenger_forecast",
            "status": "RECEIVED",
            "target_object": target,
            "result_summary": result_summary,
            "worker_stack": self._worker_stack(),
            "authority": "proposal_only",
            "execution_eligible": False,
        }
        return _signed_receipt(receipt)

    def _verifier_receipt(self, ticket: dict[str, Any], lease: dict[str, Any], now_ts: float) -> dict[str, Any]:
        target = ticket.get("target_object") if isinstance(ticket.get("target_object"), dict) else {}
        run_id = str(target.get("phase4_run_id") or "")
        candidate_key = str(target.get("candidate_key") or "")
        with sqlite3.connect(str(self.database), timeout=30.0) as conn:
            row = conn.execute(
                "SELECT payload FROM phase4_candidate_results WHERE run_id=? AND candidate_key=? LIMIT 1",
                (run_id, candidate_key),
            ).fetchone()
        reasons: list[str] = []
        candidate: dict[str, Any] = {}
        if not row:
            reasons.append("candidate_evidence_not_found")
        else:
            candidate = json.loads(row[0] or "{}")
        reconstructed_digest = _canonical_hash({
            "run_id": run_id,
            "candidate_key": candidate.get("candidate_key"),
            "robust_score": candidate.get("robust_score"),
            "normal": candidate.get("normal"),
            "recent": candidate.get("recent"),
        }) if candidate else ""
        if reconstructed_digest != str(ticket.get("input_root") or ""):
            reasons.append("subject_digest_reconstruction_mismatch")
        metric_claims_consistent = bool(candidate) and bool(candidate.get("passes_candidate_gates")) == (not candidate.get("reasons"))
        if not metric_claims_consistent:
            reasons.append("candidate_gate_claim_inconsistent")
        verdict = "PASS" if not reasons else "CONTRADICT"
        verification_summary = {
            "candidate_key": candidate_key,
            "phase4_run_id": run_id,
            "verification_scope": str(ticket.get("task_class") or "candidate_replay"),
            "candidate_gate_verdict": "PASS" if candidate.get("passes_candidate_gates") else "FAIL",
            "candidate_gate_reasons": candidate.get("reasons") or [],
            "reconstructed_subject_digest": reconstructed_digest,
            "digest_matches": reconstructed_digest == str(ticket.get("input_root") or ""),
            "metric_claims_consistent": metric_claims_consistent,
            "pbo_estimate": self._phase4_pbo(run_id),
            "reasons": reasons,
        }
        receipt = {
            "schema": "hivenance_verifier_pool_result_receipt_v1",
            "receipt_type": "verifier",
            "receipt_id": _canonical_hash({"ticket": ticket.get("ticket_id"), "worker": self.worker_id, "summary": verification_summary}),
            "ticket_id": ticket.get("ticket_id"),
            "lease_id": lease.get("lease_id"),
            "worker_id": self.worker_id,
            "created_ts": now_ts,
            "expires_ts": lease.get("expires_ts"),
            "pool_type": "verifier_pool",
            "task_class": ticket.get("task_class"),
            "phase_scope": int(ticket.get("phase_scope") or 0),
            "challenge_nonce": ticket.get("challenge_nonce"),
            "subject_digest": ticket.get("input_root"),
            "world_state_digest": ticket.get("world_state_digest"),
            "code_digest": ticket.get("code_digest"),
            "config_digest": ticket.get("config_digest"),
            "container_digest": None,
            "verification_verdict": verdict,
            "status": "RECEIVED",
            "target_object": target,
            "verification_summary": verification_summary,
            "worker_stack": self._worker_stack(),
            "authority": "verify_only",
            "execution_eligible": False,
        }
        return _signed_receipt(receipt)

    def _phase4_pbo(self, run_id: str) -> float | None:
        with sqlite3.connect(str(self.database), timeout=30.0) as conn:
            row = conn.execute("SELECT pbo_estimate FROM phase4_validation_runs WHERE run_id=? LIMIT 1", (run_id,)).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def _beast_review(
        self,
        symbol: str,
        regime_hint: Any,
        candidates: list[dict[str, Any]],
        selected: Any,
    ) -> dict[str, Any]:
        if selected is None:
            return {"status": "NOT_REQUIRED", "veto": False, "risks": ["all_deterministic_models_abstained"]}
        prompt = {
            "role": "proposal-only market forecast critic",
            "rules": [
                "Never invent prices or returns.",
                "Use only the supplied deterministic model summaries.",
                "Veto when direction is disputed, expected net is non-positive, or confidence is weak.",
                "Return JSON with keys veto (boolean) and risks (array of short strings).",
            ],
            "symbol": symbol,
            "regime_hint": regime_hint,
            "selected_model": selected.model_id,
            "candidates": candidates,
        }
        request = urllib.request.Request(
            f"{self.ollama_url}/api/generate",
            data=json.dumps({
                "model": self.ollama_model,
                "prompt": json.dumps(prompt, sort_keys=True),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0, "seed": 42, "num_predict": 160},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                envelope = json.loads(response.read().decode("utf-8"))
            review = json.loads(str(envelope.get("response") or "{}"))
            return {
                "status": "REVIEWED",
                "model": self.ollama_model,
                "veto": bool(review.get("veto")),
                "risks": [str(item) for item in (review.get("risks") or [])][:8],
            }
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            return {"status": "UNAVAILABLE", "model": self.ollama_model, "veto": False, "risks": [type(exc).__name__]}

    def _worker_stack(self) -> dict[str, Any]:
        return {
            "inference": {
                "hivenance_frozen_federation": True,
                "beast_crystal_model": self.ollama_model,
                "beast_root": "/home/byron/EdgeK-BEAST",
            },
            "verification": {
                "metatron_evidence_lineage": "/home/byron/Downloads/Metatron-triune-outbound-gate/backend/evidence_bundle.py",
                "integritas_council_contract": "/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/ainur_council.py",
                "sophia_release_judge": "/home/byron/Integritas-Mechanicus/arda_os/backend/services/mandos_protocol_judge.py",
                "seraph_fail_closed_policy": "/home/byron/Downloads/Metatron-triune-outbound-gate/backend/services/outbound_gate.py",
            },
            "authority": {
                "proposal": True,
                "verify": True,
                "promote": False,
                "execute": False,
                "live_trade": False,
            },
        }
