#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition
from strategies.volatility_breakout.hypothesis_swarm import _feature_from_payload, _feature_with_candidate_context


MODEL_ID = "candidate_triune_polyphonic_synthesis_v1"


def _latest_observations(database: Path) -> tuple[str, list[dict]]:
    uri = f"file:{database.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        latest = connection.execute(
            "SELECT run_id FROM observation_snapshots ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if latest is None:
            return "", []
        run_id = str(latest["run_id"] or "")
        rows = connection.execute(
            "SELECT * FROM observation_snapshots WHERE run_id=? ORDER BY symbol",
            (run_id,),
        ).fetchall()
    finally:
        connection.close()

    observations = []
    for row in rows:
        record = dict(row)
        try:
            payload = json.loads(record.get("payload") or "{}")
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            record.update(payload)
        observations.append(record)
    return run_id, observations


def audit(settings_path: Path, database: Path) -> dict:
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    cfg = SimpleNamespace(**settings)
    competition = HypothesisCompetition(cfg)
    model = next((item for item in competition.federated_models if item.model_id == MODEL_ID), None)
    if model is None:
        raise RuntimeError(f"{MODEL_ID} is not active in the configured federation")

    run_id, observations = _latest_observations(database)
    horizons = tuple(int(value) for value in (settings.get("phase2_horizons_seconds") or (300, 900, 3600)))
    rows = []
    refusal_counts: Counter[str] = Counter()
    challenge_failures: Counter[str] = Counter()
    for observation in observations:
        values = observation.get("values") if isinstance(observation.get("values"), dict) else {}
        feature = _feature_from_payload(values.get("feature_vector") or {})
        if feature is None:
            continue
        feature = _feature_with_candidate_context(feature, values)
        for horizon in horizons:
            forecast = model.forecast(feature, horizon_seconds=horizon)
            receipt = forecast.inputs.get("advanced_systems_synthesis", {})
            expected_move_bps = float(receipt.get("expected_move_bps") or 0.0)
            expected_cost_bps = float(forecast.expected_cost_bps or 0.0)
            for reason in forecast.reasons:
                refusal_counts[str(reason)] += 1
            for challenge in receipt.get("seraph_challenges", []):
                if not challenge.get("passed"):
                    challenge_failures[str(challenge.get("challenge_id") or "unknown")] += 1
            rows.append({
                "symbol": forecast.symbol,
                "horizon_seconds": forecast.horizon_seconds,
                "direction": forecast.direction,
                "abstain": forecast.abstain,
                "expected_net_bps": forecast.expected_net_bps,
                "expected_move_bps": round(expected_move_bps, 6),
                "expected_cost_bps": round(expected_cost_bps, 6),
                "edge_multiple": round(expected_move_bps / max(0.000001, expected_cost_bps), 6),
                "score": forecast.raw_score,
                "curriculum_stage": (receipt.get("sophia_curriculum") or {}).get("stage"),
                "resonance": (receipt.get("polyphonic_resonance") or {}).get("resonance"),
                "discord": (receipt.get("polyphonic_resonance") or {}).get("discord"),
                "sensor_quality": (receipt.get("vns_sensor") or {}).get("quality"),
                "persistence": (receipt.get("cce_cognition") or {}).get("persistence"),
                "decision_digest": (receipt.get("mandos_ledger") or {}).get("decision_digest"),
                "refusal_reasons": list(receipt.get("refusal_reasons") or ()),
            })

    proposals = [row for row in rows if not row["abstain"]]
    closest_abstentions = sorted(
        (row for row in rows if row["abstain"]),
        key=lambda row: (float(row["edge_multiple"]), float(row["score"] or 0.0)),
        reverse=True,
    )[:12]
    return {
        "schema": "hivenance_advanced_synthesis_audit_v1",
        "mode": "outcome_blind_latest_observation_audit",
        "observation_run_id": run_id,
        "symbols_examined": len(observations),
        "forecasts_examined": len(rows),
        "research_proposals": len(proposals),
        "abstentions": len(rows) - len(proposals),
        "proposal_rate": round(len(proposals) / max(1, len(rows)), 6),
        "directions": dict(Counter(row["direction"] for row in proposals)),
        "refusal_reasons": dict(refusal_counts.most_common()),
        "failed_seraph_challenges": dict(challenge_failures.most_common()),
        "source_manifest": model.synthesizer.source_manifest,
        "proposal_examples": proposals[:12],
        "closest_abstentions": closest_abstentions,
        "authority": "research_proposal_only",
        "execution_eligible": False,
        "orders_submitted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the advanced synthesis challenger on the latest observation run")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--database", type=Path, default=ROOT / "data/swarm_data.db")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = audit(args.settings, args.database)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(
            f"advanced_synthesis symbols={result['symbols_examined']} forecasts={result['forecasts_examined']} "
            f"proposals={result['research_proposals']} abstentions={result['abstentions']} "
            f"source_coverage={result['source_manifest']['available']}/{result['source_manifest']['total']} "
            "orders=0"
        )
        print("failed_challenges=" + json.dumps(result["failed_seraph_challenges"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
