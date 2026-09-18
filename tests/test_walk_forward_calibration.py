from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.walk_forward_calibration import WalkForwardForecastCalibrator


class SampleStore:
    def __init__(self, samples):
        self.samples = samples

    def get_walk_forward_calibration_samples(self, **_kwargs):
        return list(self.samples)


def config(**overrides):
    values = {
        "phase2_walk_forward_calibration_enabled": True,
        "phase2_calibration_max_samples": 100,
        "phase2_calibration_min_slice_samples": 5,
        "phase2_calibration_min_regime_samples": 6,
        "phase2_calibration_min_model_samples": 8,
        "phase2_calibration_min_distinct_symbols": 3,
        "phase2_calibration_min_distinct_time_buckets": 3,
        "phase2_calibration_stress_cost_multiple": 1.5,
        "phase2_calibration_prior_strength": 2.0,
        "phase2_calibration_one_sided_z": 1.645,
        "phase2_calibration_winsor_tail_fraction": 0.05,
        "phase2_calibration_min_stressed_lower_bound_bps": 0.0,
        "phase2_calibration_min_probability_lower_bound": 0.50,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def forecast_row():
    return {
        "forecast_id": "current",
        "model_id": "candidate_model",
        "horizon_seconds": 900,
        "expected_cost_bps": 10.0,
        "expected_move_bps": 40.0,
        "expected_net_bps": 30.0,
        "probability_positive_net": 0.70,
        "abstain": False,
        "calibration_state": "COLD_START",
        "research_route": "full_competition",
        "research_route_priority": 0,
        "execution_eligible": False,
        "inputs": {
            "symbol_class": "major",
            "regime_inputs": {"regime_hint": "trend"},
        },
    }


def samples(directional_return_bps: float, count: int = 12):
    return [
        {
            "forecast_id": f"history-{index}",
            "forecast_ts": 1_000.0 + index * 3_600.0,
            "settled_ts": 1_100.0 + index * 3_600.0,
            "symbol": ("BTC/USD", "ETH/USD", "SOL/USD")[index % 3],
            "expected_cost_bps": 10.0,
            "directional_return_bps": directional_return_bps,
            "regime_hint": "trend",
            "symbol_class": "major",
        }
        for index in range(count)
    ]


def test_positive_stressed_history_replaces_optimistic_forecast_with_lower_bounds():
    row = forecast_row()
    calibrator = WalkForwardForecastCalibrator(config(), SampleStore(samples(40.0)))

    summary = calibrator.calibrate_rows([row], cutoff_ts=100_000.0)

    receipt = row["walk_forward_calibration"]
    assert summary["allowed"] == 1
    assert receipt["decision"] == "ALLOW"
    assert row["research_route"] == "walk_forward_calibrated"
    assert row["expected_net_bps"] < 30.0
    assert row["probability_positive_net"] > 0.50
    assert row["execution_eligible"] is False


def test_sufficient_negative_history_is_refused_before_phase3_simulation():
    row = forecast_row()
    calibrator = WalkForwardForecastCalibrator(config(), SampleStore(samples(-20.0)))

    summary = calibrator.calibrate_rows([row], cutoff_ts=100_000.0)

    assert summary["refused"] == 1
    assert row["walk_forward_calibration"]["decision"] == "REFUSE"
    assert row["research_route"] == "walk_forward_calibration_refused"
    assert "stressed_return_lower_bound_below_gate" in row["walk_forward_calibration"]["reasons"]


def test_under_sampled_history_remains_explicit_research_exploration():
    row = forecast_row()
    calibrator = WalkForwardForecastCalibrator(config(), SampleStore(samples(80.0, count=3)))

    summary = calibrator.calibrate_rows([row], cutoff_ts=100_000.0)

    assert summary["insufficient_evidence"] == 1
    assert row["walk_forward_calibration"]["decision"] == "INSUFFICIENT_EVIDENCE"
    assert row["expected_net_bps"] == 30.0
    assert row["research_route"] == "full_competition"


def test_store_calibration_query_excludes_future_forecasts_and_settlements(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "calibration-cutoff.db"))
    cutoff = time.time()
    for forecast_id, forecast_ts, settled_ts in (
        ("past", cutoff - 200, cutoff - 100),
        ("future-forecast", cutoff + 10, cutoff - 10),
        ("future-settlement", cutoff - 100, cutoff + 10),
    ):
        store.conn.execute(
            """
            INSERT INTO hypothesis_forecasts
            (forecast_id, run_id, observation_run_id, ts, target_ts, venue, symbol, model_id,
             hypothesis, horizon_seconds, direction, entry_price, probability_positive_net,
             expected_move_bps, expected_cost_bps, expected_net_bps, raw_score, abstain,
             reason, settled, execution_eligible, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                forecast_id, "run", "obs", forecast_ts, forecast_ts + 60, "kraken", "BTC/USD",
                "candidate_model", "test", 900, "UP", 100.0, 0.7, 40.0, 10.0, 30.0,
                0.7, 0, "test", 1, 0,
                json.dumps({"inputs": {"symbol_class": "major", "regime_inputs": {"regime_hint": "trend"}}}),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (forecast_id, settled_ts, 101.0, 100.0, 100.0, 90.0, 1, 0.1, 1.0, "{}"),
        )
    store.conn.commit()

    rows = store.get_walk_forward_calibration_samples(
        model_id="candidate_model", horizon_seconds=900, cutoff_ts=cutoff
    )

    assert [row["forecast_id"] for row in rows] == ["past"]
