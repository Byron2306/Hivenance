from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.adversarial_validation import (
    AdversarialValidator,
    estimate_cscv_pbo,
)
from strategies.volatility_breakout.validation_lab import ValidationLabAgent


@dataclass
class Phase4Config:
    phase4_validation_enabled: bool = True
    phase4_interval_sec: int = 900
    phase4_max_rows: int = 100000
    phase4_min_candidate_trades: int = 60
    phase4_min_distinct_days: int = 30
    phase4_walk_forward_folds: int = 5
    phase4_purge_seconds: int = 300
    phase4_embargo_seconds: int = 300
    phase4_bootstrap_samples: int = 400
    phase4_bootstrap_block_size: int = 5
    phase4_dsr_min_probability: float = 0.90
    phase4_pbo_max: float = 0.25
    phase4_min_walk_forward_positive_ratio: float = 0.60
    phase4_min_parameter_positive_ratio: float = 0.70
    phase4_max_symbol_profit_concentration: float = 0.30
    phase4_max_month_profit_concentration: float = 0.35
    phase4_max_cost2_loss_bps: float = 50.0
    phase4_selection_min_probability: float = 0.50
    phase4_selection_min_expected_net_bps: float = 0.0


def build_rows(*, unstable: bool = False) -> list[dict]:
    rows: list[dict] = []
    start = 1_735_689_600.0  # 2025-01-01 UTC
    symbols = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD"]
    candidates = [
        ("breakout_continuation_v1", "market", 24.0),
        ("breakout_continuation_v1", "marketable_limit", 20.0),
        ("exhaustion_mean_reversion_v1", "market", 8.0),
        ("baseline_simple_momentum_v1", "market", 1.0),
        ("baseline_deterministic_random_v1", "market", -1.0),
    ]
    for index in range(160):
        forecast_ts = start + index * 86400.0
        symbol = symbols[index % len(symbols)]
        regime_cycle = index % 3
        expansion = (1.05, 1.65, 2.60)[regime_cycle]
        zscore = (0.4, 1.5, 2.8)[regime_cycle]
        wave = 4.0 * math.sin(index * 0.37)
        for model_id, policy, base in candidates:
            normal_return = base + wave
            if unstable and model_id == "breakout_continuation_v1":
                if index >= 96:
                    normal_return = -22.0 + wave
                if symbol != "BTC/USD":
                    normal_return -= 12.0
            for scenario, drag in (("normal", 0.0), ("cost_1_5x", 7.0), ("cost_2x", 15.0)):
                rows.append({
                    "simulation_id": f"sim-{index}-{model_id}-{policy}-{scenario}",
                    "forecast_id": f"forecast-{index}-{model_id}",
                    "model_id": model_id,
                    "hypothesis": "test",
                    "venue": "kraken",
                    "symbol": symbol,
                    "direction": "UP",
                    "order_policy": policy,
                    "scenario": scenario,
                    "status": "COMPLETED",
                    "terminal_state": "CLOSED",
                    "completed_ts": forecast_ts + 900,
                    "net_return_bps": normal_return - drag,
                    "gross_return_bps": normal_return + 20.0 - drag,
                    "fill_ratio": 1.0,
                    "profitable_after_costs": 1 if normal_return - drag > 0 else 0,
                    "execution_wired": 0,
                    "real_orders_submitted": 0,
                    "forecast_ts": forecast_ts,
                    "target_ts": forecast_ts + 900,
                    "horizon_seconds": 900,
                    "probability_positive_net": 0.70 if not model_id.startswith("baseline_") else 0.55,
                    "expected_move_bps": 55.0,
                    "expected_cost_bps": 20.0,
                    "expected_net_bps": 35.0,
                    "raw_score": 0.72,
                    "volatility_expansion": expansion,
                    "return_zscore": zscore,
                    "volume_zscore": 1.2,
                    "range_position": 0.92,
                })
    return rows


def test_consistent_candidate_survives_adversarial_gates():
    report = AdversarialValidator(Phase4Config()).validate(build_rows(), run_id="phase4-good")
    champion = report["champion"]
    assert champion is not None
    assert champion["candidate_key"].startswith("breakout_continuation_v1::")
    assert champion["normal"]["samples"] == 160
    assert champion["bootstrap"]["lower_95_bps"] > 0
    assert champion["walk_forward_positive_ratio"] >= 0.60
    assert champion["parameter_positive_ratio"] >= 0.70
    assert champion["deflated_sharpe"]["dsr_probability"] >= 0.90
    assert report["pbo"]["pbo_estimate"] <= 0.25
    assert report["readiness"]["ready_for_phase5_review"] is True
    assert report["readiness"]["execution_eligible"] is False
    assert report["real_orders_submitted"] == 0


def test_lucky_concentrated_candidate_is_rejected():
    report = AdversarialValidator(Phase4Config()).validate(build_rows(unstable=True), run_id="phase4-bad")
    breakout = next(
        item for item in report["candidate_results"]
        if item["candidate_key"] == "breakout_continuation_v1::market"
    )
    assert breakout["passes_candidate_gates"] is False
    assert any(reason in breakout["reasons"] for reason in (
        "walk_forward_instability", "bootstrap_lower_bound_not_positive",
        "symbol_holdout_instability", "symbol_profit_concentration",
    ))


def test_global_gate_closes_when_no_primary_candidate_survives():
    rows = build_rows()
    for row in rows:
        if not row["model_id"].startswith("baseline_"):
            row["net_return_bps"] = -abs(float(row["net_return_bps"])) - 5.0
            row["profitable_after_costs"] = 0
    report = AdversarialValidator(Phase4Config()).validate(rows, run_id="phase4-all-bad")
    assert report["readiness"]["ready_for_phase5_review"] is False
    assert "no_candidate_passed_all_adversarial_gates" in report["readiness"]["reasons"]
    assert report["readiness"]["execution_eligible"] is False


def test_cscv_pbo_requires_candidates_and_time_slices():
    assert estimate_cscv_pbo({"one": []})["status"] == "INSUFFICIENT_CANDIDATES"
    rows = build_rows()
    grouped = {}
    for row in rows:
        if row["scenario"] != "normal":
            continue
        grouped.setdefault(f"{row['model_id']}::{row['order_policy']}", []).append(row)
    result = estimate_cscv_pbo(grouped, slices=8)
    assert result["status"] == "OK"
    assert 0.0 <= result["pbo_estimate"] <= 1.0
    assert result["combinations"] > 0


def test_phase4_persistence_is_idempotent_and_does_not_touch_live_orders(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase4.db"))
    report = AdversarialValidator(Phase4Config()).validate(build_rows(), run_id="persisted-run")
    report.update({"started_ts": time.time() - 1, "completed_ts": time.time(), "dataset_hash": "abc123"})
    assert store.persist_phase4_validation_report(report) is True
    assert store.persist_phase4_validation_report(report) is True
    assert store.conn.execute("SELECT COUNT(*) FROM phase4_validation_runs").fetchone()[0] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM phase4_candidate_results").fetchone()[0] >= 1
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    latest = store.get_phase4_latest_report()
    assert latest["run_id"] == "persisted-run"
    assert store.get_phase4_readiness()["execution_eligible"] is False


class FakeStore:
    def __init__(self, rows):
        self.rows = rows
        self.report = None

    def get_phase4_validation_dataset(self, limit=100000):
        return self.rows[:limit]

    def persist_phase4_validation_report(self, report):
        self.report = json.loads(json.dumps(report))
        return True


class ForbiddenExecutionLab:
    def run_once(self, drive_phase2=True):
        raise AssertionError("validate-only Phase 4 must not drive Phase 3")


def test_validation_lab_validate_only_never_drives_execution():
    store = FakeStore(build_rows())
    lab = ValidationLabAgent(Phase4Config(), ForbiddenExecutionLab(), store)
    payload = lab.run_once(drive_phase3=False)
    assert payload["mode"] == "adversarial_validation_only"
    assert payload["execution_wired"] is False
    assert payload["real_orders_submitted"] == 0
    assert store.report is not None
