from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from strategies.relative_value_lab.full_organism_phase0 import (
    AUTHORITY,
    build_phase0_evidence_manifest,
    canonical_json,
    validate_campaign_identity,
    validate_phase0_manifest,
)


def _root(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/HIVENANCE_FULL_ORGANISM_RECOVERY_MASTER_PLAN_2026-09-19.md").write_text("plan")
    (tmp_path / "docs/HIVENANCE_FULL_INTEGRATION_WIRING_AUDIT_2026-09-19.md").write_text("audit")
    lock = {
        "schema": "hivenance_full_organism_phase0_lock_v1",
        "branch": "test",
        "programme_base_head": "abc",
        "active_research_evidence": {
            "campaign_id": "g1_test",
            "research_target_id": "g1rt_test",
            "research_models": ["m1", "m2"],
            "policy": {
                "min_pairs": 30,
                "min_distinct_worlds": 10,
                "confidence_z": 2.69,
                "extra_cost_stress_bps": 5.0,
                "min_mean_delta_bps": 0.0,
                "max_delta_drawdown_bps": 250.0,
            },
        },
    }
    (tmp_path / "docs/HIVENANCE_FULL_ORGANISM_PHASE0_LOCK.json").write_text(json.dumps(lock))
    return tmp_path


def _db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE g1_campaign_freeze(campaign_id TEXT,payload TEXT)")
    conn.execute("CREATE TABLE g1_research_target_freeze(target_id TEXT,payload TEXT)")
    campaign = {
        "campaign_id": "g1_test",
        "policy": {
            "min_pairs": 30,
            "min_distinct_worlds": 10,
            "confidence_z": 2.69,
            "extra_cost_stress_bps": 5.0,
            "min_mean_delta_bps": 0.0,
            "max_delta_drawdown_bps": 250.0,
        },
        "execution_eligible": False,
        "promotion_eligible": False,
    }
    target = {
        "target_id": "g1rt_test",
        "model_ids": ["m1", "m2"],
        "execution_eligible": False,
        "promotion_eligible": False,
    }
    conn.execute("INSERT INTO g1_campaign_freeze VALUES(?,?)", ("g1_test", json.dumps(campaign)))
    conn.execute("INSERT INTO g1_research_target_freeze VALUES(?,?)", ("g1rt_test", json.dumps(target)))
    conn.execute("CREATE TABLE phase5_g0_shadow_twins(id TEXT,payload TEXT)")
    conn.execute("CREATE TABLE phase5_g0_shadow_twin_settlements(id TEXT,payload TEXT)")
    conn.execute("INSERT INTO phase5_g0_shadow_twins VALUES('t1','{}')")
    conn.execute("INSERT INTO phase5_g0_shadow_twin_settlements VALUES('s1','{}')")
    conn.commit()
    return conn


def test_phase0_manifest_is_deterministic_and_non_authoritative(tmp_path):
    root = _root(tmp_path)
    db_path = tmp_path / "evidence.db"
    conn = _db(db_path)
    conn.close()
    a = build_phase0_evidence_manifest(root=root, db_path=db_path, git_head="head")
    b = build_phase0_evidence_manifest(root=root, db_path=db_path, git_head="head")
    assert canonical_json(a) == canonical_json(b)
    assert a["evidence_root"] == b["evidence_root"]
    assert a["authority"] == AUTHORITY
    assert a["execution_eligible"] is False
    assert a["promotion_eligible"] is False
    assert a["mutates_evidence"] is False
    assert validate_phase0_manifest(a) == (True, ())


def test_phase0_refuses_policy_drift(tmp_path):
    root = _root(tmp_path)
    db_path = tmp_path / "evidence.db"
    conn = _db(db_path)
    payload = json.loads(conn.execute("SELECT payload FROM g1_campaign_freeze").fetchone()[0])
    payload["policy"]["min_pairs"] = 31
    conn.execute("UPDATE g1_campaign_freeze SET payload=?", (json.dumps(payload),))
    conn.commit()
    lock = json.loads((root / "docs/HIVENANCE_FULL_ORGANISM_PHASE0_LOCK.json").read_text())
    result = validate_campaign_identity(conn, lock)
    conn.close()
    assert result["valid"] is False
    assert "campaign_policy_drift:min_pairs" in result["reasons"]


def test_phase0_refuses_authority_drift(tmp_path):
    root = _root(tmp_path)
    db_path = tmp_path / "evidence.db"
    conn = _db(db_path)
    payload = json.loads(conn.execute("SELECT payload FROM g1_research_target_freeze").fetchone()[0])
    payload["execution_eligible"] = True
    conn.execute("UPDATE g1_research_target_freeze SET payload=?", (json.dumps(payload),))
    conn.commit()
    lock = json.loads((root / "docs/HIVENANCE_FULL_ORGANISM_PHASE0_LOCK.json").read_text())
    result = validate_campaign_identity(conn, lock)
    conn.close()
    assert result["valid"] is False
    assert "target_execution_authority_drift" in result["reasons"]
