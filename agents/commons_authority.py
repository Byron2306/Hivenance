from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional


AUTHORITY_RANK = {
    "context_only": 0,
    "evidence_only": 1,
    "proposal_only": 2,
    "verify_only": 3,
    "bounded_execute": 4,
    "live_execute": 5,
}


ARTIFACT_CONTRACTS: Dict[str, Dict[str, Any]] = {
    "market_world_state_crystal_v1": {
        "artifact_class": "market_world_state_crystal",
        "max_authority": "context_only",
        "required_fields": (
            "world_state_id",
            "venue",
            "symbol",
            "observation_time_ms",
            "fresh_until_ms",
        ),
    },
    "hivenance_commons_pool_work_ticket_v1": {
        "artifact_class": "commons_pool_work_ticket",
        "max_authority": "proposal_only",
        "required_fields": (
            "ticket_id",
            "pool_type",
            "task_class",
            "phase_scope",
            "authority",
            "challenge_nonce",
            "input_root",
        ),
    },
    "hivenance_inference_pool_result_receipt_v1": {
        "artifact_class": "commons_inference_receipt",
        "max_authority": "proposal_only",
        "required_fields": (
            "receipt_id",
            "ticket_id",
            "task_class",
            "phase_scope",
            "challenge_nonce",
            "input_root",
            "output_root",
        ),
    },
    "hivenance_verifier_pool_result_receipt_v1": {
        "artifact_class": "commons_verifier_receipt",
        "max_authority": "verify_only",
        "required_fields": (
            "receipt_id",
            "ticket_id",
            "task_class",
            "phase_scope",
            "challenge_nonce",
            "subject_digest",
            "verification_verdict",
        ),
    },
    "negative_capability_crystal_v1": {
        "artifact_class": "negative_capability_crystal",
        "max_authority": "proposal_only",
        "required_fields": (
            "forecast_id",
            "symbol",
            "failure_state",
            "reason",
        ),
    },
    "hivenance_local_adoption_receipt_v1": {
        "artifact_class": "local_adoption_receipt",
        "max_authority": "proposal_only",
        "required_fields": (
            "receipt_id",
            "source_receipt_id",
            "phase_scope",
            "adoption_decision",
            "authority_ceiling",
        ),
    },
}


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def authority_at_or_below(requested: str, ceiling: str) -> bool:
    return AUTHORITY_RANK.get(str(requested or ""), -1) <= AUTHORITY_RANK.get(str(ceiling or ""), -1)


def validate_artifact_contract(
    payload: Dict[str, Any],
    *,
    expected_schema: Optional[str] = None,
    requested_authority: Optional[str] = None,
) -> Dict[str, Any]:
    schema = str((payload or {}).get("schema") or "")
    reasons: list[str] = []
    if expected_schema and schema != expected_schema:
        reasons.append("schema_mismatch")
    contract = ARTIFACT_CONTRACTS.get(schema)
    if not contract:
        reasons.append("unknown_artifact_schema")
        return {
            "ok": False,
            "schema": schema,
            "artifact_class": "unknown",
            "max_authority": None,
            "reasons": reasons,
        }
    for field in contract.get("required_fields") or ():
        value = payload.get(field)
        if value is None or value == "":
            reasons.append(f"missing_{field}")
    max_authority = str(contract.get("max_authority") or "context_only")
    if requested_authority and not authority_at_or_below(str(requested_authority), max_authority):
        reasons.append("requested_authority_exceeds_artifact_ceiling")
    return {
        "ok": not reasons,
        "schema": schema,
        "artifact_class": contract.get("artifact_class"),
        "max_authority": max_authority,
        "reasons": reasons,
    }


def validate_world_state_crystal(payload: Dict[str, Any], *, now_ms: Optional[int] = None) -> Dict[str, Any]:
    verdict = validate_artifact_contract(payload, expected_schema="market_world_state_crystal_v1")
    reasons = list(verdict.get("reasons") or [])
    current_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    if int(payload.get("fresh_until_ms") or 0) < current_ms:
        reasons.append("world_state_stale")
    if str(payload.get("execution_environment") or "") not in {"observation_only", "research_only"}:
        reasons.append("unexpected_execution_environment")
    verdict["ok"] = not reasons
    verdict["reasons"] = reasons
    verdict["world_state_id"] = payload.get("world_state_id")
    return verdict


def build_authority_boundary(
    *,
    source_payload: Dict[str, Any],
    source_family: str,
    phase_scope: int,
    requested_authority: str,
    decision: str,
    local_reproduction_verdict: str,
    reasons: Optional[list[str]] = None,
) -> Dict[str, Any]:
    contract = validate_artifact_contract(source_payload, requested_authority=requested_authority)
    source_schema = str(source_payload.get("schema") or "")
    source_digest = _canonical_hash(source_payload)
    allowed = (
        contract.get("ok") is True
        and authority_at_or_below(requested_authority, str(contract.get("max_authority") or "context_only"))
        and str(local_reproduction_verdict or "").upper() == "PASS"
        and str(decision or "").upper().startswith("ACCEPTED")
    )
    return {
        "schema": "hivenance_authority_boundary_v1",
        "source_family": str(source_family or "unknown"),
        "source_schema": source_schema,
        "source_digest": source_digest,
        "phase_scope": int(phase_scope or 0),
        "artifact_class": contract.get("artifact_class"),
        "artifact_max_authority": contract.get("max_authority"),
        "requested_authority": str(requested_authority or "proposal_only"),
        "authority_granted": str(requested_authority or "proposal_only") if allowed else "none",
        "local_reproduction_verdict": str(local_reproduction_verdict or "UNKNOWN"),
        "decision": str(decision or "REJECTED"),
        "allowed": allowed,
        "reasons": list(reasons or []) + list(contract.get("reasons") or []),
    }
