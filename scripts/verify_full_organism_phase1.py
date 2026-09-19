#!/usr/bin/env python3
"""Verify Phase-1 canonical memory/world identity against the latest observation run.

Read-only verification except for ordinary SQLite connection setup. No orders,
private endpoints, execution or promotion.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from agents.market_memory import MarketMemory
from scripts.run_phase1_observer import load_observer_config
from strategies.relative_value_lab.canonical_memory_bridge import (
    validate_binding,
    world_graph_root_from_binding,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify HiveNance Full Organism Phase 1")
    ap.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    ap.add_argument("--profile", type=Path)
    ap.add_argument("--database", type=Path)
    ap.add_argument("--memory", type=Path)
    args = ap.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/swarm_data.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    memory_path = args.memory or Path(str(
        getattr(cfg, "hivenance_market_memory_path", "data/hivenance_market_memory.db")
    ))
    if not memory_path.is_absolute() and str(memory_path) != ":memory:":
        memory_path = ROOT / memory_path

    reasons: list[str] = []
    store = DataStoreAgent(str(db_path))
    runs = store.get_observation_runs(limit=1)
    if not runs:
        reasons.append("no_observation_run")
        latest = {}
    else:
        latest = runs[0]

    payload = latest.get("payload") if isinstance(latest.get("payload"), dict) else {}
    run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
    run_id = str(run.get("run_id") or latest.get("run_id") or "")
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    if not candidates:
        reasons.append("latest_observation_has_no_candidates")

    candidate_reports: list[dict[str, Any]] = []
    memory = MarketMemory(memory_path)
    try:
        for row in candidates:
            values = row.get("values") if isinstance(row.get("values"), dict) else {}
            binding = values.get("canonical_world_binding") if isinstance(values.get("canonical_world_binding"), dict) else None
            symbol = str(row.get("symbol") or "")
            observed_at_ms = int(row.get("timestamp_ms") or 0)
            item_reasons: list[str] = []
            if binding is None:
                item_reasons.append("canonical_binding_missing")
                candidate_reports.append({
                    "symbol": symbol,
                    "valid": False,
                    "reasons": item_reasons,
                })
                continue

            valid, bind_reasons = validate_binding(
                binding, symbol=symbol, observed_at_ms=observed_at_ms
            )
            item_reasons.extend(bind_reasons)
            line = memory.line(str(binding.get("feature_memory_line_id") or ""))
            if line is None:
                item_reasons.append("feature_memory_line_missing")
            else:
                if line.get("kind") != "PHASE1_LIVE_FEATURE_OBSERVATION":
                    item_reasons.append("feature_memory_line_kind_invalid")
                if int(line.get("effective_ts_ms") or -1) != observed_at_ms:
                    item_reasons.append("feature_memory_line_timestamp_mismatch")
                if str(line.get("symbol") or "") != symbol:
                    item_reasons.append("feature_memory_line_symbol_mismatch")

            if binding.get("world_state_page_status") != "PRESENT":
                item_reasons.append("world_state_page_not_present")
            page = binding.get("world_state_page") if isinstance(binding.get("world_state_page"), dict) else {}
            latest_1m = int(((page.get("provenance") or {}).get("latest_1m_ts_ms") or 0))
            if latest_1m > observed_at_ms:
                item_reasons.append("world_state_future_data_violation")

            try:
                graph, node = world_graph_root_from_binding(binding)
                if node.world_state_id != str(binding.get("canonical_world_state_id") or ""):
                    item_reasons.append("world_graph_world_id_mismatch")
                if node.world_state_hash != str(binding.get("canonical_world_state_hash") or ""):
                    item_reasons.append("world_graph_world_hash_mismatch")
                if graph.frame.world_state_id != node.world_state_id:
                    item_reasons.append("world_graph_frame_binding_mismatch")
            except Exception as exc:
                item_reasons.append(f"world_graph_binding_error:{type(exc).__name__}")

            candidate_reports.append({
                "symbol": symbol,
                "canonical_world_state_id": binding.get("canonical_world_state_id"),
                "canonical_world_state_hash": binding.get("canonical_world_state_hash"),
                "feature_memory_line_id": binding.get("feature_memory_line_id"),
                "world_state_page_status": binding.get("world_state_page_status"),
                "valid": valid and not item_reasons,
                "reasons": item_reasons,
            })
    finally:
        memory.close()

    try:
        rows = store.conn.execute(
            "SELECT payload FROM observation_snapshots WHERE run_id=?",
            (run_id,),
        ).fetchall()
        persisted_candidates = []
        for (raw,) in rows:
            try:
                item = json.loads(raw or "{}")
            except Exception:
                item = {}
            if isinstance(item, dict):
                persisted_candidates.append(item)
        persisted_bound = sum(
            1 for row in persisted_candidates
            if isinstance(((row.get("values") or {}).get("canonical_world_binding")), dict)
        )
        if persisted_bound != len(candidates):
            reasons.append("persisted_snapshot_binding_count_mismatch")
    except Exception:
        persisted_bound = 0
        reasons.append("persisted_snapshot_binding_query_failed")

    invalid = [row for row in candidate_reports if not row.get("valid")]
    if invalid:
        reasons.append("one_or_more_candidate_bindings_invalid")

    status = "PASS" if not reasons and candidates else "REFUSE"
    result = {
        "schema": "hivenance_full_organism_phase1_verification_v1",
        "phase": 1,
        "status": status,
        "run_id": run_id,
        "database": str(db_path),
        "market_memory": str(memory_path),
        "candidates": len(candidates),
        "persisted_bound_candidates": persisted_bound,
        "candidate_reports": candidate_reports,
        "reasons": reasons,
        "execution_eligible": False,
        "promotion_eligible": False,
        "real_orders_submitted": 0,
    }
    print("HIVENANCE_FULL_ORGANISM_PHASE1")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if status == "PASS":
        print("HIVENANCE_FULL_ORGANISM_PHASE1_WORLD_IDENTITY_VERIFIED")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
