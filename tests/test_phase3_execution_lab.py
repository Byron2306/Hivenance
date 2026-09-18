from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.execution_engine import DeterministicExecutionSimulator
from strategies.volatility_breakout.execution_lab import ExecutionLabAgent


@dataclass
class Phase3Config:
    phase3_execution_lab_enabled: bool = True
    phase3_interval_sec: int = 120
    phase3_max_forecasts_per_cycle: int = 50
    phase3_max_simulations_per_forecast: int = 20
    phase3_simulated_equity_usd: float = 1000.0
    phase3_risk_fraction: float = 0.0005
    phase3_sleeve_fraction: float = 0.02
    phase3_max_notional_usd: float = 25.0
    phase3_max_depth_participation: float = 0.01
    phase3_base_latency_ms: float = 180.0
    phase3_max_slippage_bps: float = 75.0
    phase3_min_data_quality: float = 0.99
    phase3_min_notional_usd: float = 5.0
    phase3_maker_fee_bps: float = 10.0
    phase3_taker_fee_bps: float = 20.0
    phase3_max_entry_spread_bps: float = 60.0
    phase3_min_expected_net_bps: float = 0.0
    phase3_min_probability_positive_net: float = 0.0
    phase3_min_historical_realized_net_bps: float = float("-inf")
    phase3_min_historical_samples: int = 0
    phase3_min_regime_historical_realized_net_bps: float = float("-inf")
    phase3_min_regime_historical_samples: int = 0
    phase3_prefer_research_candidates: bool = False
    phase3_prefer_regime_alignment: bool = True
    phase3_frontier_min_settled_trades: int = 5
    phase3_frontier_min_mean_realized_net_bps: float = 2.5
    phase3_prefer_profitability_frontier: bool = True
    phase3_regime_reentry_recent_window: int = 4
    phase3_regime_reentry_min_samples: int = 3
    phase3_regime_reentry_min_mean_realized_net_bps: float = 2.0
    phase3_min_cost_survival_ratio: float = 1.0
    phase3_unique_per_symbol_cohort: bool = True
    phase3_failure_feedback_enabled: bool = True
    phase3_failure_feedback_lookback: int = 12
    phase3_failure_feedback_penalty_scale: float = 1.0
    phase3_worker_counterfactual_simulation_enabled: bool = True
    phase3_calibration_exploration_fallback_enabled: bool = True
    phase3_calibration_exploration_model_ids: tuple[str, ...] = ()
    phase3_calibration_exploration_order_policies: tuple[str, ...] = ("passive_then_chase",)
    phase3_readiness_min_completed: int = 1
    phase3_readiness_max_mean_2x_loss_bps: float = 500.0
    phase2_settlement_tolerance_sec: int = 600


def candidate(direction: str = "UP", forecast_id: str = "forecast-1") -> dict:
    now = time.time()
    return {
        "forecast_id": forecast_id,
        "forecast_ts": now - 600,
        "target_ts": now - 300,
        "settled_ts": now - 250,
        "venue": "kraken",
        "symbol": "ETH/USD",
        "model_id": "breakout_continuation_v1",
        "hypothesis": "breakout_continuation",
        "horizon_seconds": 300,
        "direction": direction,
        "entry_price": 100.0,
        "exit_price": 102.0 if direction == "UP" else 98.0,
        "probability_positive_net": 0.64,
        "expected_move_bps": 180.0,
        "expected_cost_bps": 25.0,
        "expected_net_bps": 155.0,
        "directional_return_bps": 200.0,
        "net_return_bps": 175.0,
        "forecast_payload": {
            "inputs": {"cost": {"spread_bps": 4.0}},
        },
        "entry_observation": {
            "symbol": "ETH/USD",
            "venue": "kraken",
            "timestamp_ms": int((now - 600) * 1000),
            "price": 100.0,
            "quote_volume_24h": 100_000_000.0,
            "spread_bps": 4.0,
            "depth_usd_25bps": 500_000.0,
            "data_quality": 1.0,
            "values": {
                "feature_vector": {
                    "atr_pct": 0.01,
                    "realized_volatility_fast": 0.008,
                    "quote_volume_24h": 100_000_000.0,
                    "spread_bps": 4.0,
                    "depth_usd_25bps": 500_000.0,
                    "data_quality": 1.0,
                }
            },
        },
    }


def test_simulator_is_deterministic_and_never_live():
    sim = DeterministicExecutionSimulator(Phase3Config())
    source = candidate()
    first = sim.simulate(source, run_id="run-a", order_policy="market", scenario="normal")
    second = sim.simulate(source, run_id="run-a", order_policy="market", scenario="normal")
    assert first.to_dict() == second.to_dict()
    assert first.status == "COMPLETED"
    assert first.terminal_state in {"CLOSED", "RECONCILED"}
    assert len(first.fills) == 2
    assert first.execution_wired is False
    assert first.real_orders_submitted == 0
    assert first.intent.live_eligible is False
    assert first.costs.total_cost_bps > 0
    assert first.costs.gross_signal_bps == 200.0
    assert first.costs.entry_fee_bps > 0
    assert first.costs.exit_fee_bps > 0
    assert first.costs.taker_fee_bps > 0
    assert first.costs.fee_verified is False
    assert "fee_verification" in first.diagnostics
    assert first.diagnostics.get("symbol_class") == "ultra_liquid_major"


def test_down_forecasts_remain_synthetic_in_spot_only_lab():
    sim = DeterministicExecutionSimulator(Phase3Config())
    result = sim.simulate(candidate(direction="DOWN"), run_id="run-b", order_policy="market", scenario="normal")
    assert result.status == "COMPLETED"
    assert result.spot_executable is False
    assert "synthetic" in str(result.diagnostics.get("spot_note", "")).lower()
    assert result.real_orders_submitted == 0


def test_stressed_passive_policy_can_expire_without_fake_fill():
    sim = DeterministicExecutionSimulator(Phase3Config())
    expired = None
    for index in range(200):
        result = sim.simulate(
            candidate(forecast_id=f"passive-{index}"),
            run_id="run-c",
            order_policy="passive_post_only",
            scenario="liquidity_stress",
        )
        if result.status == "EXPIRED":
            expired = result
            break
    assert expired is not None
    assert expired.fill_ratio == 0
    assert expired.fills == ()
    assert expired.costs.missed_fill_opportunity_bps >= 0
    assert "late_entry_or_missed_fill" in list(expired.diagnostics.get("failure_causes") or [])


def test_simulation_persistence_is_idempotent_and_does_not_touch_live_orders(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase3.db"))
    result = DeterministicExecutionSimulator(Phase3Config()).simulate(
        candidate(), run_id="run-d", order_policy="market", scenario="normal"
    ).to_dict()
    assert store.persist_execution_simulation(result) is True
    assert store.persist_execution_simulation(result) is True
    assert store.conn.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM simulated_fills").fetchone()[0] == 2
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    scorecard = store.get_execution_scorecard()
    assert scorecard["real_orders_submitted"] == 0
    assert scorecard["execution_wiring_violations"] == 0
    assert len(scorecard["rows"]) == 1
    assert scorecard["symbol_class_breakdown"]


def test_execution_scorecard_tracks_worker_executor_pairs(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase3-worker-executor.db"))
    source = candidate()
    source["model_id"] = "worker_signal_rsi2_v1"
    source["hypothesis"] = "legacy_connors_rsi2_worker"
    source["forecast_id"] = "worker-rsi2-forecast"
    forecast_payload = {
        "forecast_id": source["forecast_id"],
        "model_id": source["model_id"],
        "hypothesis": source["hypothesis"],
        "direction": source["direction"],
        "horizon_seconds": source["horizon_seconds"],
        "inputs": {
            "worker_signal": {"family": "mean_reversion"},
            "worker_signal_receipt": {
                "worker_id": "WORKER-RSI2",
                "execution_authority": "none",
                "orders_submitted": 0,
            },
            "worker_counterfactual": {
                "schema": "hivenance_worker_counterfactual_settlement_v1",
                "execution_authority": "none",
            },
            "regime_inputs": {"regime_hint": "quiet_range"},
            "cohort_bucket": "mean_reversion",
            "symbol_class": "ultra_liquid_major",
        },
    }
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
            source["forecast_id"], "run", "obs", source["forecast_ts"], source["target_ts"],
            source["venue"], source["symbol"], source["model_id"], source["hypothesis"],
            source["horizon_seconds"], source["direction"], source["entry_price"], 0.6,
            20.0, 30.0, -10.0, 1.0, 0, "worker_signal_counterfactual_cost_refused",
            1, 0, json.dumps(forecast_payload),
        ),
    )
    store.conn.commit()
    result = DeterministicExecutionSimulator(Phase3Config()).simulate(
        source, run_id="run-worker", order_policy="market", scenario="normal"
    ).to_dict()
    assert store.persist_execution_simulation(result) is True

    scorecard = store.get_execution_scorecard()
    worker_rows = scorecard.get("worker_executor_breakdown") or []

    assert worker_rows
    assert worker_rows[0]["worker_id"] == "WORKER-RSI2"
    assert worker_rows[0]["model_id"] == "worker_signal_rsi2_v1"
    assert worker_rows[0]["order_policy"] == "market"
    assert worker_rows[0]["scenario"] == "normal"
    assert worker_rows[0]["signal_mode"] == "counterfactual"
    assert (scorecard.get("worker_executor_posteriors") or [])[0]["execution_authority"] == "none"


def test_phase3_candidate_pool_admits_worker_counterfactuals_for_simulation(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=10.0,
        phase3_min_probability_positive_net=0.58,
        phase3_min_historical_samples=3,
        phase3_min_regime_historical_samples=2,
        phase3_worker_counterfactual_simulation_enabled=True,
    )

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "phase3-worker-counterfactual-candidates.db"), coordinator=Coordinator(cfg))
    now = time.time()
    forecast_id = "worker-counterfactual-admit"
    forecast_payload = {
        "forecast_id": forecast_id,
        "model_id": "worker_signal_rsi2_v1",
        "hypothesis": "legacy_connors_rsi2_worker",
        "direction": "UP",
        "horizon_seconds": 300,
        "inputs": {
            "worker_signal": {"family": "mean_reversion"},
            "worker_signal_receipt": {
                "worker_id": "WORKER-RSI2",
                "execution_authority": "none",
                "orders_submitted": 0,
            },
            "worker_counterfactual": {
                "schema": "hivenance_worker_counterfactual_settlement_v1",
                "execution_authority": "none",
            },
            "regime_inputs": {"regime_hint": "quiet_range"},
            "cohort_bucket": "mean_reversion",
            "symbol_class": "ultra_liquid_major",
        },
    }
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
            forecast_id, "run", "obs", now - 600, now - 300, "kraken", "ETH/USD",
            "worker_signal_rsi2_v1", "legacy_connors_rsi2_worker", 300, "UP", 100.0,
            0.50, 10.0, 30.0, -20.0, 1.0, 0,
            "worker_signal_counterfactual_cost_refused", 1, 0, json.dumps(forecast_payload),
        ),
    )
    store.conn.execute(
        """
        INSERT INTO hypothesis_outcomes
        (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
         net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (forecast_id, now - 250, 100.4, 40.0, 40.0, 10.0, 1, 0.25, 30.0, "{}"),
    )
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=5)
    meta = store.get_phase3_candidate_meta()

    assert any(row.get("forecast_id") == forecast_id for row in selected)
    picked = next(row for row in selected if row.get("forecast_id") == forecast_id)
    assert picked["worker_counterfactual_candidate"] is True
    assert meta["filters"]["worker_counterfactual_simulation_enabled"] is True


class NoopHypothesis:
    def run_once(self):
        raise AssertionError("replay-only execution lab must not drive Phase 2")


def seed_settled_forecast(store: DataStoreAgent) -> None:
    now_ms = int(time.time() * 1000)
    entry_ms = now_ms - 400_000
    target_ms = entry_ms + 300_000
    store.handle_event({
        "buzz": {"type": "buzz.observation.snapshot", "source": "TEST", "ts": entry_ms},
        "payload": {
            "status": "HEALTHY",
            "dataset_hash": "entry-hash",
            "run": {
                "run_id": "obs-entry", "started_at_ms": entry_ms,
                "completed_at_ms": entry_ms, "venue": "kraken",
                "symbols_attempted": 1, "symbols_successful": 1,
                "symbols_eligible": 1, "mean_data_quality": 1.0, "errors": [],
            },
            "candidates": [{
                "symbol": "ETH/USD", "venue": "kraken", "timestamp_ms": entry_ms,
                "price": 100.0, "quote_volume_24h": 100_000_000.0,
                "spread_bps": 4.0, "depth_usd_25bps": 500_000.0,
                "data_quality": 1.0, "observation_eligible": True,
                "execution_eligible": False, "rejection_reasons": [],
                "values": {"feature_vector": {
                    "atr_pct": 0.01, "realized_volatility_fast": 0.008,
                    "spread_bps": 4.0, "depth_usd_25bps": 500_000.0,
                    "data_quality": 1.0,
                }},
            }],
        },
    })
    store.handle_event({
        "buzz": {"type": "buzz.hypothesis.snapshot", "source": "TEST", "ts": entry_ms},
        "payload": {
            "status": "HEALTHY", "dataset_hash": "hyp-hash",
            "run": {
                "run_id": "hyp-entry", "observation_run_id": "obs-entry",
                "started_at_ms": entry_ms, "completed_at_ms": entry_ms,
                "venue": "kraken", "symbols_evaluated": 1,
                "forecasts_total": 1, "non_abstain_forecasts": 1,
                "abstentions": 0,
            },
            "forecasts": [{
                "forecast_id": "settled-forecast", "run_id": "hyp-entry",
                "observation_run_id": "obs-entry", "timestamp_ms": entry_ms,
                "target_timestamp_ms": target_ms, "venue": "kraken",
                "symbol": "ETH/USD", "model_id": "breakout_continuation_v1",
                "hypothesis": "breakout_continuation", "horizon_seconds": 300,
                "direction": "UP", "entry_price": 100.0,
                "probability_positive_net": 0.65, "expected_move_bps": 180.0,
                "expected_cost_bps": 25.0, "expected_net_bps": 155.0,
                "raw_score": 0.7, "abstain": False, "reason": "test",
                "execution_eligible": False, "inputs": {},
            }],
        },
    })
    future_ms = target_ms + 1_000
    store.handle_event({
        "buzz": {"type": "buzz.observation.snapshot", "source": "TEST", "ts": future_ms},
        "payload": {
            "status": "HEALTHY", "dataset_hash": "future-hash",
            "run": {
                "run_id": "obs-future", "started_at_ms": future_ms,
                "completed_at_ms": future_ms, "venue": "kraken",
                "symbols_attempted": 1, "symbols_successful": 1,
                "symbols_eligible": 1, "mean_data_quality": 1.0, "errors": [],
            },
            "candidates": [{
                "symbol": "ETH/USD", "venue": "kraken", "timestamp_ms": future_ms,
                "price": 102.0, "quote_volume_24h": 100_000_000.0,
                "spread_bps": 4.0, "depth_usd_25bps": 500_000.0,
                "data_quality": 1.0, "observation_eligible": True,
                "execution_eligible": False, "rejection_reasons": [], "values": {},
            }],
        },
    })
    settled = store.settle_mature_hypothesis_forecasts(now_ts=time.time(), tolerance_sec=120)
    assert settled["settled"] == 1


def test_execution_lab_runs_policy_tournament_without_phase2_or_live_execution(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "lab.db"))
    seed_settled_forecast(store)
    lab = ExecutionLabAgent(Phase3Config(), NoopHypothesis(), store)
    payload = lab.run_once(drive_phase2=False)
    assert payload["mode"] == "execution_simulation_only"
    assert payload["run"]["forecasts_examined"] == 1
    assert payload["run"]["simulations_created"] == 20
    assert payload["real_orders_submitted"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0] == 20
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    # Idempotent rerun creates no duplicate simulations.
    repeat = lab.run_once(drive_phase2=False)
    assert repeat["run"]["simulations_created"] == 0
    assert repeat["run"]["forecasts_examined"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM simulated_orders").fetchone()[0] == 20
    scorecard = store.get_execution_scorecard()
    assert "slice_execution_breakdown" in scorecard
    assert any(
        row.get("hypothesis") == "breakout_continuation"
        and row.get("order_policy")
        and row.get("scenario")
        for row in scorecard["slice_execution_breakdown"]
    )


def test_high_vol_profile_admits_niche_hostile_liquidity_for_simulation(tmp_path: Path):
    cfg = Phase3Config()
    cfg.profile_name = "high_vol_low_stakes"
    cfg.phase3_allow_niche_hostile_liquidity = True
    cfg.phase3_interval_sec = 10
    cfg.phase3_min_interval_sec = 1
    cfg.phase3_max_entry_spread_bps = 200.0
    cfg.phase3_min_data_quality = 0.5
    cfg.phase1_observation_min_depth_usd_25bps = 1_000.0
    store = DataStoreAgent(str(tmp_path / "phase3-niche-admission.db"))
    lab = ExecutionLabAgent(cfg, NoopHypothesis(), store)
    now_ms = int(time.time() * 1000)
    candidate_row = candidate(forecast_id="niche-hostile")
    candidate_row["symbol"] = "WILD/USD"
    candidate_row["entry_observation"] = {
        "symbol": "WILD/USD",
        "venue": "kraken",
        "timestamp_ms": now_ms,
        "price": 0.02,
        "quote_volume_24h": 75_000.0,
        "spread_bps": 80.0,
        "depth_usd_25bps": 1_500.0,
        "data_quality": 0.8,
        "values": {
            "symbol_class": "hostile_liquidity",
            "feature_vector": {
                "realized_volatility_fast": 0.03,
                "spread_bps": 80.0,
                "depth_usd_25bps": 1_500.0,
                "quote_volume_24h": 75_000.0,
                "data_quality": 0.8,
            },
        },
    }

    receipt = lab._phase3_admission_receipt(candidate_row, now_ms)

    assert lab.interval_sec == 10
    assert receipt["admitted"] is True
    assert "hostile_liquidity_class" not in receipt["rejection_causes"]


def test_execution_scorecard_emits_coalition_posteriors_and_challenger_comparison(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "coalition-scorecard.db"))
    seed_settled_forecast(store)
    payload = {
        "forecast_id": "settled-forecast",
        "model_id": "worker_coalition_meta_v1",
        "hypothesis": "worker_coalition_meta",
        "direction": "UP",
        "horizon_seconds": 300,
        "venue": "kraken",
        "inputs": {
            "cohort_bucket": "event_driven",
            "symbol_class": "ultra_liquid_major",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.80},
            "worker_coalition_receipt": {
                "schema": "hivenance_worker_coalition_receipt_v1",
                "execution_authority": "none",
                "orders_submitted": 0,
                "symbol_class_budget": {
                    "schema": "hivenance_worker_coalition_symbol_class_budget_v1",
                    "budget_name": "major",
                    "symbol_class": "ultra_liquid_major",
                    "families": ["trend", "breakout", "momentum", "mean_reversion"],
                    "authority": "research_budget_only",
                },
                "coalition": {
                    "allowed_voters": 3,
                    "agreement": 0.72,
                    "direction": "UP",
                },
            },
        },
    }
    store.conn.execute(
        """
        UPDATE hypothesis_forecasts
        SET model_id='worker_coalition_meta_v1',
            hypothesis='worker_coalition_meta',
            payload=?
        WHERE forecast_id='settled-forecast'
        """,
        (json.dumps(payload),),
    )
    store.conn.commit()

    lab = ExecutionLabAgent(Phase3Config(), NoopHypothesis(), store)
    result = lab.run_once(drive_phase2=False)
    scorecard = store.get_execution_scorecard()

    assert result["run"]["simulations_created"] == 20
    assert scorecard["coalition_execution_breakdown"]
    assert scorecard["coalition_slice_posteriors"]
    posterior = scorecard["coalition_slice_posteriors"][0]
    assert posterior["schema"] == "coalition_execution_slice_posterior_v1"
    assert posterior["symbol_class"] == "ultra_liquid_major"
    assert posterior["budget_name"] == "major"
    assert posterior["execution_authority"] == "none"
    assert "beats_primary_federated_challenger_oos" in posterior
    assert scorecard["coalition_challenger_comparison"]["schema"] == "phase3_coalition_challenger_comparison_v1"


def test_phase3_refuses_forecast_with_sufficient_failed_walk_forward_calibration(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "calibration-refusal.db"))
    seed_settled_forecast(store)
    raw = store.conn.execute(
        "SELECT payload FROM hypothesis_forecasts WHERE forecast_id='settled-forecast'"
    ).fetchone()[0]
    payload = json.loads(raw or "{}")
    payload["walk_forward_calibration"] = {
        "evidence_sufficient": True,
        "decision": "REFUSE",
        "reasons": ["stressed_return_lower_bound_below_gate"],
    }
    store.conn.execute(
        "UPDATE hypothesis_forecasts SET payload=? WHERE forecast_id='settled-forecast'",
        (json.dumps(payload),),
    )
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=5)
    meta = store.get_phase3_candidate_meta()

    assert selected == []
    assert meta["rejections"]["walk_forward_calibration_refused"] == 1


def test_execution_lab_uses_replay_only_fallback_when_calibration_blocks_all_candidates(tmp_path: Path):
    cfg = Phase3Config(
        phase3_calibration_exploration_model_ids=("breakout_continuation_v1",),
    )
    store = DataStoreAgent(str(tmp_path / "calibration-fallback.db"))
    seed_settled_forecast(store)
    raw = store.conn.execute(
        "SELECT payload FROM hypothesis_forecasts WHERE forecast_id='settled-forecast'"
    ).fetchone()[0]
    payload = json.loads(raw or "{}")
    payload["walk_forward_calibration"] = {
        "evidence_sufficient": True,
        "decision": "REFUSE",
        "reasons": ["stressed_return_lower_bound_below_gate"],
    }
    store.conn.execute(
        "UPDATE hypothesis_forecasts SET payload=? WHERE forecast_id='settled-forecast'",
        (json.dumps(payload),),
    )
    store.conn.commit()

    lab = ExecutionLabAgent(cfg, NoopHypothesis(), store)
    result = lab.run_once(drive_phase2=False)

    assert result["status"] == "HEALTHY"
    assert result["candidate_intake"]["formal_selected_count"] == 0
    assert result["candidate_intake"]["exploration_fallback"]["authority"] == "research_replay_only"
    assert result["run"]["simulations_created"] > 0
    assert result["real_orders_submitted"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    assert all(
        candidate.get("research_route") == "calibration_exploration_fallback"
        and candidate.get("execution_eligible") is False
        for candidate in result["candidate_intake"]["sample"]
    )


def test_phase3_candidate_filters_do_not_use_future_settlements_as_history(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=5.0,
        phase3_min_probability_positive_net=0.50,
        phase3_min_historical_realized_net_bps=0.0,
        phase3_min_historical_samples=1,
        phase3_min_regime_historical_realized_net_bps=0.0,
        phase3_min_regime_historical_samples=1,
    )

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "no-lookahead.db"), coordinator=Coordinator(cfg))
    now = time.time()

    def insert_forecast(row: dict, *, settled_ts: float, regime_hint: str = "trend_expansion") -> None:
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
                row["forecast_id"], "run", f"obs-{row['forecast_id']}", row["forecast_ts"], row["target_ts"], "kraken",
                row["symbol"], row["model_id"], row["hypothesis"], row["horizon_seconds"],
                row["direction"], row["entry_price"], row["probability_positive_net"],
                row["expected_move_bps"], row["expected_cost_bps"], row["expected_net_bps"],
                row.get("raw_score", 0.7), 0, "test", 1, 0,
                json.dumps({"inputs": {"regime_inputs": {"regime_hint": regime_hint}}}),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["forecast_id"], settled_ts, row["exit_price"], row["directional_return_bps"],
                row["directional_return_bps"], row["net_return_bps"], 1 if row["net_return_bps"] > 0 else 0,
                0.1, 5.0, "{}",
            ),
        )

    candidate_row = candidate(forecast_id="candidate-now")
    candidate_row["model_id"] = "candidate_freqai_transparent_linear_v1"
    candidate_row["forecast_ts"] = now - 600
    candidate_row["target_ts"] = now - 300
    candidate_row["settled_ts"] = now - 250

    future_history = candidate(forecast_id="future-history")
    future_history["model_id"] = "candidate_freqai_transparent_linear_v1"
    future_history["forecast_ts"] = now - 100
    future_history["target_ts"] = now + 100
    future_history["settled_ts"] = now + 200
    future_history["net_return_bps"] = 40.0

    insert_forecast(candidate_row, settled_ts=candidate_row["settled_ts"])
    insert_forecast(future_history, settled_ts=future_history["settled_ts"])
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=5)
    meta = store.get_phase3_candidate_meta()

    selected_ids = [row["forecast_id"] for row in selected]
    assert "candidate-now" not in selected_ids
    assert "future-history" in selected_ids
    assert meta["rejections"]["insufficient_history"] >= 1


def test_phase3_candidate_prefers_slice_matched_history(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=5.0,
        phase3_min_probability_positive_net=0.50,
        phase3_min_historical_realized_net_bps=0.0,
        phase3_min_historical_samples=1,
        phase3_min_regime_historical_realized_net_bps=0.0,
        phase3_min_regime_historical_samples=1,
        phase3_unique_per_symbol_cohort=False,
    )

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "slice-priors.db"), coordinator=Coordinator(cfg))
    now = time.time()

    def insert_forecast(
        row: dict,
        *,
        settled_ts: float | None = None,
        regime_hint: str = "trend_expansion",
        cohort_bucket: str = "event_driven",
        symbol_class: str = "ultra_liquid_major",
    ) -> None:
        payload = {
            "inputs": {
                "cohort_bucket": cohort_bucket,
                "symbol_class": symbol_class,
                "regime_inputs": {"regime_hint": regime_hint},
            }
        }
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
                row["forecast_id"], "run", f"obs-{row['forecast_id']}", row["forecast_ts"], row["target_ts"], "kraken",
                row["symbol"], row["model_id"], row["hypothesis"], row["horizon_seconds"],
                row["direction"], row["entry_price"], row["probability_positive_net"],
                row["expected_move_bps"], row["expected_cost_bps"], row["expected_net_bps"],
                row.get("raw_score", 0.7), 0, "test", 1, 0, json.dumps(payload),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["forecast_id"], settled_ts if settled_ts is not None else row["settled_ts"], row["exit_price"],
                row["directional_return_bps"], row["directional_return_bps"], row["net_return_bps"],
                1 if row["net_return_bps"] > 0 else 0, 0.1, 5.0, "{}",
            ),
        )
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
             depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
             data_quality, observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"obs-{row['forecast_id']}", row["forecast_ts"], "kraken", row["symbol"],
                row["entry_price"], 100_000_000.0, 4.0, 500_000.0,
                1.3, 0.9, 0.1, 1.0, 1, 0, "[]",
                json.dumps({
                    "symbol": row["symbol"],
                    "venue": "kraken",
                    "timestamp_ms": 0,
                    "price": row["entry_price"],
                    "spread_bps": 4.0,
                    "depth_usd_25bps": 500_000.0,
                    "data_quality": 1.0,
                    "values": {
                        "feature_vector": {
                            "atr_pct": 0.01,
                            "realized_volatility_fast": 0.008,
                            "spread_bps": 4.0,
                            "depth_usd_25bps": 500_000.0,
                            "data_quality": 1.0,
                        },
                        "regime_inputs": {"regime_hint": regime_hint},
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                    },
                }),
            ),
        )

    slice_history = candidate(forecast_id="slice-history")
    slice_history["model_id"] = "candidate_model_a"
    slice_history["symbol"] = "ETH/USD"
    slice_history["forecast_ts"] = now - 1200
    slice_history["target_ts"] = now - 900
    slice_history["settled_ts"] = now - 850
    slice_history["net_return_bps"] = 26.0
    insert_forecast(slice_history)

    generic_history = candidate(forecast_id="generic-history")
    generic_history["model_id"] = "candidate_model_b"
    generic_history["symbol"] = "ETH/USD"
    generic_history["forecast_ts"] = now - 1180
    generic_history["target_ts"] = now - 880
    generic_history["settled_ts"] = now - 840
    generic_history["net_return_bps"] = 55.0
    insert_forecast(
        generic_history,
        regime_hint="trend_expansion",
        cohort_bucket="breakout_retest",
        symbol_class="general_liquid",
    )

    slice_winner = candidate(forecast_id="slice-winner")
    slice_winner["model_id"] = "candidate_model_a"
    slice_winner["symbol"] = "ETH/USD"
    slice_winner["forecast_ts"] = now - 600
    slice_winner["target_ts"] = now - 300
    slice_winner["settled_ts"] = now - 250
    slice_winner["expected_net_bps"] = 90.0
    slice_winner["net_return_bps"] = 12.0
    insert_forecast(slice_winner)

    generic_only = candidate(forecast_id="generic-only")
    generic_only["model_id"] = "candidate_model_b"
    generic_only["symbol"] = "ETH/USD"
    generic_only["forecast_ts"] = now - 590
    generic_only["target_ts"] = now - 290
    generic_only["settled_ts"] = now - 240
    generic_only["expected_net_bps"] = 90.0
    generic_only["net_return_bps"] = 12.0
    insert_forecast(
        generic_only,
        regime_hint="trend_expansion",
        cohort_bucket="event_driven",
        symbol_class="general_liquid",
    )
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=5)
    meta = store.get_phase3_candidate_meta()

    assert selected[0]["forecast_id"] == "slice-winner"
    assert selected[0]["slice_historical_samples"] >= 1
    assert float(selected[0]["slice_historical_mean_net_bps"] or 0.0) > 0.0
    assert any(
        row.get("forecast_id") == "slice-winner"
        and row.get("symbol_class") == "ultra_liquid_major"
        and int(row.get("slice_historical_samples") or 0) >= 1
        for row in meta.get("sample", [])
    )


def test_phase3_candidate_prefers_recent_slice_evidence_over_stale_average(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=5.0,
        phase3_min_probability_positive_net=0.50,
        phase3_min_historical_realized_net_bps=-100.0,
        phase3_min_historical_samples=1,
        phase3_min_regime_historical_realized_net_bps=-100.0,
        phase3_min_regime_historical_samples=1,
        phase3_unique_per_symbol_cohort=False,
    )
    cfg.phase3_recency_window = 2

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "recent-slice-priors.db"), coordinator=Coordinator(cfg))
    now = time.time()

    def insert_forecast(
        row: dict,
        *,
        regime_hint: str = "trend_expansion",
        cohort_bucket: str = "event_driven",
        symbol_class: str = "ultra_liquid_major",
    ) -> None:
        payload = {
            "inputs": {
                "cohort_bucket": cohort_bucket,
                "symbol_class": symbol_class,
                "regime_inputs": {"regime_hint": regime_hint},
            }
        }
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
                row["forecast_id"], "run", f"obs-{row['forecast_id']}", row["forecast_ts"], row["target_ts"], "kraken",
                row["symbol"], row["model_id"], row["hypothesis"], row["horizon_seconds"],
                row["direction"], row["entry_price"], row["probability_positive_net"],
                row["expected_move_bps"], row["expected_cost_bps"], row["expected_net_bps"],
                row.get("raw_score", 0.7), 0, "test", 1, 0, json.dumps(payload),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["forecast_id"], row["settled_ts"], row["exit_price"], row["directional_return_bps"],
                row["directional_return_bps"], row["net_return_bps"], 1 if row["net_return_bps"] > 0 else 0,
                0.1, 5.0, "{}",
            ),
        )
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
             depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
             data_quality, observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"obs-{row['forecast_id']}", row["forecast_ts"], "kraken", row["symbol"],
                row["entry_price"], 100_000_000.0, 4.0, 500_000.0,
                1.3, 0.9, 0.1, 1.0, 1, 0, "[]",
                json.dumps({
                    "symbol": row["symbol"],
                    "venue": "kraken",
                    "timestamp_ms": 0,
                    "price": row["entry_price"],
                    "spread_bps": 4.0,
                    "depth_usd_25bps": 500_000.0,
                    "data_quality": 1.0,
                    "values": {
                        "feature_vector": {
                            "atr_pct": 0.01,
                            "realized_volatility_fast": 0.008,
                            "spread_bps": 4.0,
                            "depth_usd_25bps": 500_000.0,
                            "data_quality": 1.0,
                        },
                        "regime_inputs": {"regime_hint": regime_hint},
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                    },
                }),
            ),
        )

    stale_good_1 = candidate(forecast_id="stale-good-1")
    stale_good_1["model_id"] = "candidate_model_a"
    stale_good_1["symbol"] = "ETH/USD"
    stale_good_1["forecast_ts"] = now - 2200
    stale_good_1["target_ts"] = now - 1900
    stale_good_1["settled_ts"] = now - 1850
    stale_good_1["net_return_bps"] = 60.0
    insert_forecast(stale_good_1)

    stale_good_2 = candidate(forecast_id="stale-good-2")
    stale_good_2["model_id"] = "candidate_model_a"
    stale_good_2["symbol"] = "ETH/USD"
    stale_good_2["forecast_ts"] = now - 1800
    stale_good_2["target_ts"] = now - 1500
    stale_good_2["settled_ts"] = now - 1450
    stale_good_2["net_return_bps"] = 50.0
    insert_forecast(stale_good_2)

    recent_bad_1 = candidate(forecast_id="recent-bad-1")
    recent_bad_1["model_id"] = "candidate_model_a"
    recent_bad_1["symbol"] = "ETH/USD"
    recent_bad_1["forecast_ts"] = now - 1200
    recent_bad_1["target_ts"] = now - 900
    recent_bad_1["settled_ts"] = now - 850
    recent_bad_1["net_return_bps"] = -40.0
    insert_forecast(recent_bad_1)

    recent_bad_2 = candidate(forecast_id="recent-bad-2")
    recent_bad_2["model_id"] = "candidate_model_a"
    recent_bad_2["symbol"] = "ETH/USD"
    recent_bad_2["forecast_ts"] = now - 1000
    recent_bad_2["target_ts"] = now - 700
    recent_bad_2["settled_ts"] = now - 650
    recent_bad_2["net_return_bps"] = -35.0
    insert_forecast(recent_bad_2)

    stale_positive_other_slice = candidate(forecast_id="other-slice-history")
    stale_positive_other_slice["model_id"] = "candidate_model_b"
    stale_positive_other_slice["symbol"] = "ETH/USD"
    stale_positive_other_slice["forecast_ts"] = now - 1200
    stale_positive_other_slice["target_ts"] = now - 900
    stale_positive_other_slice["settled_ts"] = now - 850
    stale_positive_other_slice["net_return_bps"] = 22.0
    insert_forecast(
        stale_positive_other_slice,
        cohort_bucket="breakout_retest",
        symbol_class="general_liquid",
    )

    decayed_candidate = candidate(forecast_id="decayed-candidate")
    decayed_candidate["model_id"] = "candidate_model_a"
    decayed_candidate["symbol"] = "ETH/USD"
    decayed_candidate["forecast_ts"] = now - 600
    decayed_candidate["target_ts"] = now - 300
    decayed_candidate["settled_ts"] = now - 250
    decayed_candidate["expected_net_bps"] = 92.0
    decayed_candidate["net_return_bps"] = 5.0
    insert_forecast(decayed_candidate)

    fresh_candidate = candidate(forecast_id="fresh-candidate")
    fresh_candidate["model_id"] = "candidate_model_b"
    fresh_candidate["symbol"] = "ETH/USD"
    fresh_candidate["forecast_ts"] = now - 590
    fresh_candidate["target_ts"] = now - 290
    fresh_candidate["settled_ts"] = now - 240
    fresh_candidate["expected_net_bps"] = 90.0
    fresh_candidate["net_return_bps"] = 8.0
    insert_forecast(
        fresh_candidate,
        cohort_bucket="breakout_retest",
        symbol_class="general_liquid",
    )
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=5)
    meta = store.get_phase3_candidate_meta()

    selected_ids = [row["forecast_id"] for row in selected]
    assert selected_ids.index("fresh-candidate") < selected_ids.index("decayed-candidate")
    decayed_meta = next(row for row in meta.get("sample", []) if row.get("forecast_id") == "decayed-candidate")
    assert float(decayed_meta.get("slice_historical_mean_net_bps") or 0.0) > 0.0
    assert float(decayed_meta.get("recent_slice_historical_mean_net_bps") or 0.0) < 0.0


def test_phase3_candidate_prefers_profitability_frontier_slice(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=5.0,
        phase3_min_probability_positive_net=0.50,
        phase3_min_historical_realized_net_bps=-100.0,
        phase3_min_historical_samples=1,
        phase3_min_regime_historical_realized_net_bps=-100.0,
        phase3_min_regime_historical_samples=1,
        phase3_frontier_min_settled_trades=5,
        phase3_frontier_min_mean_realized_net_bps=2.5,
        phase3_prefer_profitability_frontier=True,
        phase3_unique_per_symbol_cohort=False,
    )

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "frontier-priors.db"), coordinator=Coordinator(cfg))
    now = time.time()

    def insert_forecast(
        row: dict,
        *,
        regime_hint: str = "trend_expansion",
        cohort_bucket: str = "event_driven",
        symbol_class: str = "ultra_liquid_major",
    ) -> None:
        payload = {
            "inputs": {
                "cohort_bucket": cohort_bucket,
                "symbol_class": symbol_class,
                "regime_inputs": {"regime_hint": regime_hint},
            }
        }
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
                row["forecast_id"], "run", f"obs-{row['forecast_id']}", row["forecast_ts"], row["target_ts"], "kraken",
                row["symbol"], row["model_id"], row["hypothesis"], row["horizon_seconds"],
                row["direction"], row["entry_price"], row["probability_positive_net"],
                row["expected_move_bps"], row["expected_cost_bps"], row["expected_net_bps"],
                row.get("raw_score", 0.7), 0, "test", 1, 0, json.dumps(payload),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["forecast_id"], row["settled_ts"], row["exit_price"], row["directional_return_bps"],
                row["directional_return_bps"], row["net_return_bps"], 1 if row["net_return_bps"] > 0 else 0,
                0.1, 5.0, "{}",
            ),
        )
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
             depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
             data_quality, observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"obs-{row['forecast_id']}", row["forecast_ts"], "kraken", row["symbol"],
                row["entry_price"], 100_000_000.0, 4.0, 500_000.0,
                1.3, 0.9, 0.1, 1.0, 1, 0, "[]",
                json.dumps({
                    "symbol": row["symbol"],
                    "venue": "kraken",
                    "timestamp_ms": 0,
                    "price": row["entry_price"],
                    "spread_bps": 4.0,
                    "depth_usd_25bps": 500_000.0,
                    "data_quality": 1.0,
                    "values": {
                        "feature_vector": {
                            "atr_pct": 0.01,
                            "realized_volatility_fast": 0.008,
                            "spread_bps": 4.0,
                            "depth_usd_25bps": 500_000.0,
                            "data_quality": 1.0,
                        },
                        "regime_inputs": {"regime_hint": regime_hint},
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                    },
                }),
            ),
        )

    for index in range(6):
        strong = candidate(forecast_id=f"frontier-strong-{index}")
        strong["model_id"] = "candidate_model_frontier"
        strong["symbol"] = "ETH/USD" if index % 2 == 0 else "BTC/USD"
        strong["forecast_ts"] = now - 2000 + index * 10
        strong["target_ts"] = strong["forecast_ts"] + 300
        strong["settled_ts"] = strong["target_ts"] + 50
        strong["net_return_bps"] = 8.0
        strong["expected_net_bps"] = 40.0
        insert_forecast(strong, regime_hint="trend_expansion")

    weak_hist = candidate(forecast_id="frontier-weak-history")
    weak_hist["model_id"] = "candidate_model_nonfrontier"
    weak_hist["symbol"] = "ETH/USD"
    weak_hist["forecast_ts"] = now - 1200
    weak_hist["target_ts"] = now - 900
    weak_hist["settled_ts"] = now - 850
    weak_hist["net_return_bps"] = 1.0
    weak_hist["expected_net_bps"] = 40.0
    insert_forecast(weak_hist, regime_hint="trend_expansion")

    frontier_live = candidate(forecast_id="frontier-live")
    frontier_live["model_id"] = "candidate_model_frontier"
    frontier_live["symbol"] = "ETH/USD"
    frontier_live["forecast_ts"] = now - 600
    frontier_live["target_ts"] = now - 300
    frontier_live["settled_ts"] = now - 250
    frontier_live["expected_net_bps"] = 35.0
    frontier_live["net_return_bps"] = 3.0
    insert_forecast(frontier_live, regime_hint="trend_expansion")

    nonfrontier_live = candidate(forecast_id="nonfrontier-live")
    nonfrontier_live["model_id"] = "candidate_model_nonfrontier"
    nonfrontier_live["symbol"] = "ETH/USD"
    nonfrontier_live["forecast_ts"] = now - 590
    nonfrontier_live["target_ts"] = now - 290
    nonfrontier_live["settled_ts"] = now - 240
    nonfrontier_live["expected_net_bps"] = 45.0
    nonfrontier_live["net_return_bps"] = 4.0
    insert_forecast(nonfrontier_live, regime_hint="trend_expansion")
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=5)
    meta = store.get_phase3_candidate_meta()
    selected_ids = [row["forecast_id"] for row in selected]

    assert selected_ids.index("frontier-live") < selected_ids.index("nonfrontier-live")
    frontier_meta = next(row for row in meta.get("sample", []) if row.get("forecast_id") == "frontier-live")
    assert frontier_meta.get("frontier_eligible") is True
    assert float(frontier_meta.get("frontier_regime_mean_net_bps") or 0.0) >= 2.5


def test_phase3_candidate_allows_regime_reentry_when_recent_same_regime_block_recovers(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=5.0,
        phase3_min_probability_positive_net=0.50,
        phase3_min_historical_realized_net_bps=-100.0,
        phase3_min_historical_samples=1,
        phase3_min_regime_historical_realized_net_bps=0.0,
        phase3_min_regime_historical_samples=1,
        phase3_regime_reentry_recent_window=3,
        phase3_regime_reentry_min_samples=3,
        phase3_regime_reentry_min_mean_realized_net_bps=2.0,
        phase3_unique_per_symbol_cohort=False,
    )

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "phase3-regime-reentry.db"), coordinator=Coordinator(cfg))
    now = time.time()

    def insert_forecast(
        row: dict,
        *,
        regime_hint: str = "quiet_range",
        cohort_bucket: str = "event_driven",
        symbol_class: str = "ultra_liquid_major",
    ) -> None:
        payload = {
            "inputs": {
                "cohort_bucket": cohort_bucket,
                "symbol_class": symbol_class,
                "regime_inputs": {"regime_hint": regime_hint},
            }
        }
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
                row["forecast_id"], "run", f"obs-{row['forecast_id']}", row["forecast_ts"], row["target_ts"], "kraken",
                row["symbol"], row["model_id"], row["hypothesis"], row["horizon_seconds"],
                row["direction"], row["entry_price"], row["probability_positive_net"],
                row["expected_move_bps"], row["expected_cost_bps"], row["expected_net_bps"],
                row.get("raw_score", 0.7), 0, "test", 1, 0, json.dumps(payload),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["forecast_id"], row["settled_ts"], row["exit_price"], row["directional_return_bps"],
                row["directional_return_bps"], row["net_return_bps"], 1 if row["net_return_bps"] > 0 else 0,
                0.1, 5.0, "{}",
            ),
        )
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
             depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
             data_quality, observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"obs-{row['forecast_id']}", row["forecast_ts"], "kraken", row["symbol"],
                row["entry_price"], 100_000_000.0, 4.0, 500_000.0,
                1.3, 0.9, 0.1, 1.0, 1, 0, "[]",
                json.dumps({
                    "symbol": row["symbol"],
                    "venue": "kraken",
                    "timestamp_ms": 0,
                    "price": row["entry_price"],
                    "spread_bps": 4.0,
                    "depth_usd_25bps": 500_000.0,
                    "data_quality": 1.0,
                    "values": {
                        "feature_vector": {
                            "atr_pct": 0.01,
                            "realized_volatility_fast": 0.008,
                            "spread_bps": 4.0,
                            "depth_usd_25bps": 500_000.0,
                            "data_quality": 1.0,
                        },
                        "regime_inputs": {"regime_hint": regime_hint},
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                    },
                }),
            ),
        )

    model_id = "candidate_model_recovering"
    for index, net_bps in enumerate((-12.0, -11.0, -10.0, -9.0, 5.0, 6.0, 7.0), start=1):
        row = candidate(forecast_id=f"reentry-history-{index}")
        row["model_id"] = model_id
        row["symbol"] = "ETH/USD"
        row["forecast_ts"] = now - 2000 + index * 60
        row["target_ts"] = row["forecast_ts"] + 300
        row["settled_ts"] = row["target_ts"] + 50
        row["net_return_bps"] = net_bps
        row["expected_net_bps"] = 35.0
        insert_forecast(row)

    recovering_live = candidate(forecast_id="recovering-live")
    recovering_live["model_id"] = model_id
    recovering_live["symbol"] = "ETH/USD"
    recovering_live["forecast_ts"] = now - 300
    recovering_live["target_ts"] = now - 60
    recovering_live["settled_ts"] = now - 30
    recovering_live["expected_net_bps"] = 32.0
    recovering_live["net_return_bps"] = 4.0
    insert_forecast(recovering_live)
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=10)
    meta = store.get_phase3_candidate_meta()
    selected_ids = [row["forecast_id"] for row in selected]

    assert "recovering-live" in selected_ids
    recovering_meta = next(row for row in meta.get("sample", []) if row.get("forecast_id") == "recovering-live")
    assert recovering_meta.get("regime_reentry_eligible") is True
    assert float(recovering_meta.get("regime_historical_mean_net_bps") or 0.0) < 0.0
    assert float(recovering_meta.get("recent_regime_historical_mean_net_bps") or 0.0) >= 2.0


def test_phase3_candidate_infers_symbol_class_from_observation_when_missing(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=5.0,
        phase3_min_probability_positive_net=0.50,
        phase3_min_historical_realized_net_bps=-100.0,
        phase3_min_historical_samples=1,
        phase3_min_regime_historical_realized_net_bps=-100.0,
        phase3_min_regime_historical_samples=1,
        phase3_unique_per_symbol_cohort=False,
    )

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "phase3-symbol-class-infer.db"), coordinator=Coordinator(cfg))
    now = time.time()

    def insert_forecast(row: dict, *, with_symbol_class: bool) -> None:
        inputs = {
            "cohort_bucket": "event_driven",
            "regime_inputs": {"regime_hint": "trend_expansion"},
        }
        if with_symbol_class:
            inputs["symbol_class"] = "general_liquid"
        payload = {"inputs": inputs}
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
                row["forecast_id"], "run", f"obs-{row['forecast_id']}", row["forecast_ts"], row["target_ts"], "kraken",
                row["symbol"], row["model_id"], row["hypothesis"], row["horizon_seconds"],
                row["direction"], row["entry_price"], row["probability_positive_net"],
                row["expected_move_bps"], row["expected_cost_bps"], row["expected_net_bps"],
                row.get("raw_score", 0.7), 0, "test", 1, 0, json.dumps(payload),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["forecast_id"], row["settled_ts"], row["exit_price"], row["directional_return_bps"],
                row["directional_return_bps"], row["net_return_bps"], 1 if row["net_return_bps"] > 0 else 0,
                0.1, 5.0, "{}",
            ),
        )
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
             depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
             data_quality, observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"obs-{row['forecast_id']}", row["forecast_ts"], "kraken", row["symbol"],
                row["entry_price"], 120_000_000.0, 4.0, 600_000.0,
                1.3, 0.9, 0.1, 1.0, 1, 0, "[]",
                json.dumps({
                    "symbol": row["symbol"],
                    "venue": "kraken",
                    "timestamp_ms": 0,
                    "price": row["entry_price"],
                    "quote_volume_24h": 120_000_000.0,
                    "spread_bps": 4.0,
                    "depth_usd_25bps": 600_000.0,
                    "data_quality": 1.0,
                    "values": {
                        "feature_vector": {
                            "atr_pct": 0.01,
                            "realized_volatility_fast": 0.008,
                            "spread_bps": 4.0,
                            "depth_usd_25bps": 600_000.0,
                            "quote_volume_24h": 120_000_000.0,
                            "data_quality": 1.0,
                        },
                        "regime_inputs": {"regime_hint": "trend_expansion"},
                        "cohort_bucket": "event_driven",
                    },
                }),
            ),
        )

    history = candidate(forecast_id="history-infer")
    history["model_id"] = "candidate_model_a"
    history["forecast_ts"] = now - 1200
    history["target_ts"] = now - 900
    history["settled_ts"] = now - 850
    history["net_return_bps"] = 10.0
    insert_forecast(history, with_symbol_class=False)

    live = candidate(forecast_id="live-infer")
    live["model_id"] = "candidate_model_a"
    live["forecast_ts"] = now - 600
    live["target_ts"] = now - 300
    live["settled_ts"] = now - 250
    live["net_return_bps"] = 6.0
    insert_forecast(live, with_symbol_class=False)
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=5)
    assert selected
    inferred = next(row for row in selected if row["forecast_id"] == "live-infer")
    assert inferred["symbol_class"] == "ultra_liquid_major"


def test_execution_scorecard_tracks_failure_causes(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase3-failure-causes.db"))
    sim = DeterministicExecutionSimulator(Phase3Config())

    wide = candidate(forecast_id="wide-spread")
    wide["entry_observation"]["spread_bps"] = 90.0
    wide["entry_observation"]["values"]["feature_vector"]["spread_bps"] = 90.0
    rejected = sim.simulate(wide, run_id="run-wide", order_policy="market", scenario="normal").to_dict()
    assert store.persist_execution_simulation(rejected) is True

    expired = None
    for index in range(300):
        result = sim.simulate(
            candidate(forecast_id=f"expire-{index}"),
            run_id="run-expire",
            order_policy="passive_post_only",
            scenario="liquidity_stress",
        )
        if result.status == "EXPIRED":
            expired = result.to_dict()
            break
    assert expired is not None
    assert store.persist_execution_simulation(expired) is True

    scorecard = store.get_execution_scorecard()
    causes = {row["cause"]: row["count"] for row in scorecard.get("failure_cause_breakdown", [])}
    assert causes.get("spread_too_wide", 0) >= 1
    assert causes.get("late_entry_or_missed_fill", 0) >= 1


def test_phase3_candidate_penalizes_repeated_failure_causes_in_slice_feedback(tmp_path: Path):
    cfg = Phase3Config(
        phase3_min_expected_net_bps=5.0,
        phase3_min_probability_positive_net=0.50,
        phase3_min_historical_realized_net_bps=-100.0,
        phase3_min_historical_samples=1,
        phase3_min_regime_historical_realized_net_bps=-100.0,
        phase3_min_regime_historical_samples=1,
        phase3_unique_per_symbol_cohort=False,
        phase3_failure_feedback_enabled=True,
        phase3_failure_feedback_lookback=6,
        phase3_failure_feedback_penalty_scale=1.0,
    )

    class Coordinator:
        def __init__(self, cfg):
            self.cfg = cfg

    store = DataStoreAgent(str(tmp_path / "phase3-failure-feedback.db"), coordinator=Coordinator(cfg))
    sim = DeterministicExecutionSimulator(cfg)
    now = time.time()

    def insert_forecast(
        row: dict,
        *,
        model_id: str,
        hypothesis: str = "breakout_continuation",
        regime_hint: str = "trend_expansion",
        cohort_bucket: str = "event_driven",
        symbol_class: str = "ultra_liquid_major",
    ) -> None:
        payload = {
            "inputs": {
                "cohort_bucket": cohort_bucket,
                "symbol_class": symbol_class,
                "regime_inputs": {"regime_hint": regime_hint},
            }
        }
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
                row["forecast_id"], "run", f"obs-{row['forecast_id']}", row["forecast_ts"], row["target_ts"], "kraken",
                row["symbol"], model_id, hypothesis, row["horizon_seconds"],
                row["direction"], row["entry_price"], row["probability_positive_net"],
                row["expected_move_bps"], row["expected_cost_bps"], row["expected_net_bps"],
                row.get("raw_score", 0.7), 0, "test", 1, 0, json.dumps(payload),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["forecast_id"], row["settled_ts"], row["exit_price"], row["directional_return_bps"],
                row["directional_return_bps"], row["net_return_bps"], 1 if row["net_return_bps"] > 0 else 0,
                0.1, 5.0, "{}",
            ),
        )
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
             depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
             data_quality, observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"obs-{row['forecast_id']}", row["forecast_ts"], "kraken", row["symbol"],
                row["entry_price"], 100_000_000.0, 4.0, 500_000.0,
                1.3, 0.9, 0.1, 1.0, 1, 0, "[]",
                json.dumps({
                    "symbol": row["symbol"],
                    "venue": "kraken",
                    "timestamp_ms": 0,
                    "price": row["entry_price"],
                    "quote_volume_24h": 100_000_000.0,
                    "spread_bps": 4.0,
                    "depth_usd_25bps": 500_000.0,
                    "data_quality": 1.0,
                    "values": {
                        "feature_vector": {
                            "atr_pct": 0.01,
                            "realized_volatility_fast": 0.008,
                            "quote_volume_24h": 100_000_000.0,
                            "spread_bps": 4.0,
                            "depth_usd_25bps": 500_000.0,
                            "data_quality": 1.0,
                        },
                        "regime_inputs": {"regime_hint": regime_hint},
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                    },
                }),
            ),
        )

    penalized_model = "candidate_model_penalized"
    clean_model = "candidate_model_clean"

    for idx in range(3):
        hist = candidate(forecast_id=f"pen-history-{idx}")
        hist["symbol"] = "ETH/USD"
        hist["forecast_ts"] = now - 3000 + idx * 60
        hist["target_ts"] = hist["forecast_ts"] + 300
        hist["settled_ts"] = hist["target_ts"] + 50
        hist["net_return_bps"] = 10.0
        insert_forecast(hist, model_id=penalized_model)
        sim_row = sim.simulate(hist, run_id=f"sim-pen-{idx}", order_policy="market", scenario="normal").to_dict()
        sim_row["diagnostics"]["failure_causes"] = ["wrong_regime", "false_breakout"]
        assert store.persist_execution_simulation(sim_row) is True

    for idx in range(3):
        hist = candidate(forecast_id=f"clean-history-{idx}")
        hist["symbol"] = "BTC/USD"
        hist["forecast_ts"] = now - 3000 + idx * 60
        hist["target_ts"] = hist["forecast_ts"] + 300
        hist["settled_ts"] = hist["target_ts"] + 50
        hist["net_return_bps"] = 10.0
        insert_forecast(hist, model_id=clean_model)
        sim_row = sim.simulate(hist, run_id=f"sim-clean-{idx}", order_policy="market", scenario="normal").to_dict()
        sim_row["diagnostics"]["failure_causes"] = []
        assert store.persist_execution_simulation(sim_row) is True

    live_pen = candidate(forecast_id="pen-live")
    live_pen["symbol"] = "ETH/USD"
    live_pen["forecast_ts"] = now - 600
    live_pen["target_ts"] = now - 300
    live_pen["settled_ts"] = now - 250
    live_pen["expected_net_bps"] = 90.0
    live_pen["net_return_bps"] = 8.0
    insert_forecast(live_pen, model_id=penalized_model)

    live_clean = candidate(forecast_id="clean-live")
    live_clean["symbol"] = "BTC/USD"
    live_clean["forecast_ts"] = now - 590
    live_clean["target_ts"] = now - 290
    live_clean["settled_ts"] = now - 240
    live_clean["expected_net_bps"] = 90.0
    live_clean["net_return_bps"] = 8.0
    insert_forecast(live_clean, model_id=clean_model)
    store.conn.commit()

    selected = store.get_phase3_forecast_candidates(limit=10)
    meta = store.get_phase3_candidate_meta()
    selected_ids = [row["forecast_id"] for row in selected]
    assert selected_ids.index("clean-live") < selected_ids.index("pen-live")
    penalized_meta = next(row for row in meta.get("sample", []) if row.get("forecast_id") == "pen-live")
    assert float(penalized_meta.get("failure_feedback_penalty_bps_equiv") or 0.0) > 0.0
    top_causes = penalized_meta.get("failure_feedback_top_causes") or []
    assert any(item.get("cause") == "wrong_regime" for item in top_causes)
