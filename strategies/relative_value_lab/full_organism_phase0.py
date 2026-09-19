"""Phase-0 evidence freeze helpers for the HiveNance Full Organism Recovery programme.

Research-only. This module fingerprints existing evidence; it never rewrites it.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

AUTHORITY = "HIVENANCE_FULL_ORGANISM_PHASE0_EVIDENCE_FREEZE_ONLY"
LOCK_PATH = Path("docs/HIVENANCE_FULL_ORGANISM_PHASE0_LOCK.json")
MASTER_PLAN_PATH = Path("docs/HIVENANCE_FULL_ORGANISM_RECOVERY_MASTER_PLAN_2026-09-19.md")
AUDIT_PATH = Path("docs/HIVENANCE_FULL_INTEGRATION_WIRING_AUDIT_2026-09-19.md")
EVIDENCE_TABLES = (
    "g1_campaign_freeze",
    "g1_research_target_freeze",
    "phase5_g0_shadow_twins",
    "phase5_g0_shadow_twin_settlements",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_programme_lock(root: Path) -> dict[str, Any]:
    payload = json.loads((root / LOCK_PATH).read_text())
    if payload.get("schema") != "hivenance_full_organism_phase0_lock_v1":
        raise ValueError("phase0_lock_schema_invalid")
    return payload


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (str(table),),
    ).fetchone()
    return row is not None


def _table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    cur = conn.execute(f'SELECT * FROM "{table}"')
    cols = [str(d[0]) for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    # Stable ordering independent of SQLite row-return order.
    rows.sort(key=canonical_json)
    return rows


def table_manifest(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    exists = _table_exists(conn, table)
    rows = _table_rows(conn, table) if exists else []
    payload = {"table": str(table), "exists": exists, "rows": rows}
    return {
        "table": str(table),
        "exists": exists,
        "row_count": len(rows),
        "content_sha256": sha256_text(canonical_json(payload)),
    }


def _payload_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    cols = [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    if "payload" not in cols:
        return []
    out: list[dict[str, Any]] = []
    for (raw,) in conn.execute(f'SELECT payload FROM "{table}"').fetchall():
        try:
            payload = json.loads(raw or "{}")
        except Exception:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def validate_campaign_identity(conn: sqlite3.Connection, lock: Mapping[str, Any]) -> dict[str, Any]:
    expected = lock["active_research_evidence"]
    campaign_id = str(expected["campaign_id"])
    target_id = str(expected["research_target_id"])

    campaigns = _payload_rows(conn, "g1_campaign_freeze")
    targets = _payload_rows(conn, "g1_research_target_freeze")
    campaign = next((x for x in campaigns if str(x.get("campaign_id") or "") == campaign_id), None)
    target = next((x for x in targets if str(x.get("target_id") or "") == target_id), None)

    reasons: list[str] = []
    if campaign is None:
        reasons.append("frozen_campaign_missing")
    if target is None:
        reasons.append("frozen_research_target_missing")

    if campaign is not None:
        frozen_policy = dict(campaign.get("policy") or {})
        for key, value in dict(expected.get("policy") or {}).items():
            if frozen_policy.get(key) != value:
                reasons.append(f"campaign_policy_drift:{key}")
        if campaign.get("execution_eligible") is not False:
            reasons.append("campaign_execution_authority_drift")
        if campaign.get("promotion_eligible") is not False:
            reasons.append("campaign_promotion_authority_drift")

    if target is not None:
        if target.get("execution_eligible") is not False:
            reasons.append("target_execution_authority_drift")
        if target.get("promotion_eligible") is not False:
            reasons.append("target_promotion_authority_drift")
        mids = tuple(target.get("model_ids") or ())
        expected_mids = tuple(expected.get("research_models") or ())
        if mids and mids != expected_mids:
            reasons.append("research_model_roster_drift")

    return {
        "campaign_id": campaign_id,
        "research_target_id": target_id,
        "campaign_present": campaign is not None,
        "target_present": target is not None,
        "valid": not reasons,
        "reasons": tuple(reasons),
    }


def build_phase0_evidence_manifest(
    *,
    root: Path,
    db_path: Path,
    git_head: str | None = None,
) -> dict[str, Any]:
    lock = load_programme_lock(root)
    conn = sqlite3.connect(str(db_path))
    try:
        tables = tuple(table_manifest(conn, table) for table in EVIDENCE_TABLES)
        identity = validate_campaign_identity(conn, lock)
    finally:
        conn.close()

    sources = {
        "programme_lock": sha256_file(root / LOCK_PATH),
        "master_plan": sha256_file(root / MASTER_PLAN_PATH),
        "integration_audit": sha256_file(root / AUDIT_PATH),
    }
    evidence_root = sha256_text(canonical_json({
        "tables": tables,
        "identity": identity,
        "sources": sources,
    }))
    return {
        "schema": "hivenance_full_organism_phase0_evidence_manifest_v1",
        "phase": 0,
        "authority": AUTHORITY,
        "branch": str(lock.get("branch") or ""),
        "git_head": git_head,
        "programme_base_head": lock.get("programme_base_head"),
        "campaign_identity": identity,
        "tables": tables,
        "source_sha256": sources,
        "evidence_root": evidence_root,
        "execution_eligible": False,
        "promotion_eligible": False,
        "mutates_evidence": False,
    }


def validate_phase0_manifest(manifest: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if manifest.get("authority") != AUTHORITY:
        reasons.append("phase0_authority_invalid")
    if manifest.get("execution_eligible") is not False:
        reasons.append("phase0_execution_authority_invalid")
    if manifest.get("promotion_eligible") is not False:
        reasons.append("phase0_promotion_authority_invalid")
    if manifest.get("mutates_evidence") is not False:
        reasons.append("phase0_mutation_boundary_invalid")
    identity = manifest.get("campaign_identity") or {}
    if not bool(identity.get("valid")):
        reasons.extend(str(x) for x in identity.get("reasons") or ("campaign_identity_invalid",))
    for table in manifest.get("tables") or ():
        if table.get("table") in {"g1_campaign_freeze", "g1_research_target_freeze"} and not table.get("exists"):
            reasons.append(f"required_table_missing:{table.get('table')}")
    return (not reasons, tuple(reasons))
