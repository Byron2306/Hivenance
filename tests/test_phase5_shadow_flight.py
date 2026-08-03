from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.shadow_flight import build_freeze_from_phase4, frozen_config_hash
from strategies.volatility_breakout.shadow_lab import ShadowFlightAgent


@dataclass
class Phase5Config:
    exchange: str = "kraken"
    phase5_shadow_enabled: bool = True
    phase5_interval_sec: int = 120
    phase5_shadow_max_intents_per_cycle: int = 25
    phase5_shadow_reference_notional_usd: float = 10.0
    phase5_shadow_stop_distance_bps: float = 250.0
    phase5_shadow_entry_latency_ms: float = 0.0
    phase5_shadow_chase_timeout_sec: int = 30
    phase5_shadow_settlement_tolerance_sec: int = 900
    phase5_shadow_min_data_quality: float = 0.99
    phase5_shadow_max_spread_bps: float = 60.0
    phase5_readiness_min_distinct_days: int = 30
    phase5_readiness_min_settled: int = 100
    phase5_readiness_max_cost_mae_bps: float = 20.0
    phase5_readiness_min_fill_ratio: float = 0.50
    phase5_readiness_require_positive_mean: bool = True
    phase3_simulated_equity_usd: float = 1000.0
    phase3_risk_fraction: float = 0.0005
    phase3_sleeve_fraction: float = 0.02
    phase3_max_notional_usd: float = 25.0
    phase3_max_depth_participation: float = 0.01
    phase3_min_notional_usd: float = 5.0
    phase3_maker_fee_bps: float = 10.0
    phase3_taker_fee_bps: float = 20.0
    phase3_max_entry_spread_bps: float = 60.0
    phase3_max_slippage_bps: float = 75.0
    phase2_horizons_seconds: tuple[int, ...] = (300, 900, 3600)
    phase2_min_data_quality: float = 0.99
    phase2_minimum_edge_multiple: float = 2.0
    phase2_federation_enabled: bool = True
    phase2_federation_min_data_quality: float = 0.99
    phase2_federation_minimum_edge_multiple: float = 1.1
    phase2_federation_score_scale: float = 1.15
    phase2_federation_freqai_confidence_floor: float = 0.28
    phase2_breakout_min_expansion: float = 1.25
    phase2_breakout_min_volume_zscore: float = 0.5
    phase2_breakout_min_return_zscore: float = 0.75
    phase2_reversion_min_stretch_zscore: float = 1.5
    phase2_reversion_min_range_extreme: float = 0.85


def phase4_report(run_id="phase4-approved", candidate="breakout_continuation_v1::market"):
    model, policy = candidate.split("::", 1)
    return {
        "run_id": run_id,
        "status": "HEALTHY",
        "dataset_hash": "phase4-dataset",
        "started_ts": 1.0,
        "completed_ts": 2.0,
        "validator_version": "test",
        "rows_examined": 1000,
        "primary_rows": 500,
        "candidate_count": 2,
        "pbo": {"pbo_estimate": 0.1},
        "champion": {
            "candidate_key": candidate,
            "model_id": model,
            "order_policy": policy,
            "passes_candidate_gates": True,
        },
        "candidate_results": [], "fold_results": [], "holdout_results": [], "perturbation_results": [],
        "readiness": {"ready_for_phase5_review": True, "execution_eligible": False, "reasons": []},
        "execution_wired": False, "real_orders_submitted": 0,
    }


def persist_observation(store, run_id, ts, price):
    store.handle_event({
        "buzz": {"type": "buzz.observation.snapshot", "source": "TEST", "ts": int(ts * 1000)},
        "payload": {
            "status": "HEALTHY", "dataset_hash": run_id,
            "run": {"run_id": run_id, "started_at_ms": int(ts * 1000), "completed_at_ms": int(ts * 1000),
                    "venue": "kraken", "symbols_attempted": 1, "symbols_successful": 1,
                    "symbols_eligible": 1, "mean_data_quality": 1.0, "errors": []},
            "candidates": [{
                "symbol": "ETH/USD", "venue": "kraken", "timestamp_ms": int(ts * 1000),
                "price": price, "quote_volume_24h": 100_000_000.0, "spread_bps": 4.0,
                "depth_usd_25bps": 500_000.0, "data_quality": 1.0,
                "observation_eligible": True, "execution_eligible": False,
                "rejection_reasons": [], "values": {"volatility_expansion": 1.8},
            }],
        },
    })


def persist_forecast(store, ts, target):
    store.handle_event({
        "buzz": {"type": "buzz.hypothesis.snapshot", "source": "TEST", "ts": int(ts * 1000)},
        "payload": {
            "status": "HEALTHY", "dataset_hash": "hyp",
            "run": {"run_id": "hyp-shadow", "observation_run_id": "obs-entry",
                    "started_at_ms": int(ts * 1000), "completed_at_ms": int(ts * 1000),
                    "venue": "kraken", "symbols_evaluated": 1, "forecasts_total": 1,
                    "non_abstain_forecasts": 1, "abstentions": 0},
            "forecasts": [{
                "forecast_id": "forecast-shadow", "run_id": "hyp-shadow", "observation_run_id": "obs-entry",
                "timestamp_ms": int(ts * 1000), "target_timestamp_ms": int(target * 1000),
                "venue": "kraken", "symbol": "ETH/USD", "model_id": "breakout_continuation_v1",
                "hypothesis": "breakout_continuation", "horizon_seconds": int(target - ts),
                "direction": "UP", "entry_price": 100.0, "probability_positive_net": 0.70,
                "expected_move_bps": 100.0, "expected_cost_bps": 25.0, "expected_net_bps": 75.0,
                "raw_score": 0.8, "abstain": False, "reason": "test", "execution_eligible": False,
                "inputs": {},
            }],
        },
    })


def approve(store, cfg, approved_ts):
    report = phase4_report()
    assert store.persist_phase4_validation_report(report)
    freeze = build_freeze_from_phase4(report, approved_by="Byron", approved_ts=approved_ts, cfg=cfg)
    assert store.persist_phase5_freeze(asdict(freeze))
    return freeze


def test_phase5_stays_locked_without_human_approval(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "locked.db"))
    payload = ShadowFlightAgent(Phase5Config(), None, store).run_once(drive_upstream=False)
    assert payload["status"] == "LOCKED_AWAITING_HUMAN_APPROVAL"
    assert payload["intents_created"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_phase5_creates_never_transmitted_intent_and_is_idempotent(tmp_path: Path):
    cfg = Phase5Config()
    store = DataStoreAgent(str(tmp_path / "shadow.db"))
    base = time.time() - 30
    approve(store, cfg, base - 10)
    persist_observation(store, "obs-entry", base, 100.0)
    persist_forecast(store, base, base + 300)
    lab = ShadowFlightAgent(cfg, None, store)
    payload = lab.run_once(drive_upstream=False)
    assert payload["status"] == "SHADOW_ACTIVE"
    assert payload["intents_created"] == 1
    intent = store.get_phase5_shadow_intents(limit=1)[0]
    assert intent["transmission_status"] == "NEVER_TRANSMITTED"
    assert intent["private_endpoint_called"] == 0
    assert intent["credentials_used"] == 0
    assert intent["live_eligible"] is False
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    repeat = lab.run_once(drive_upstream=False)
    assert repeat["intents_created"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM phase5_shadow_intents").fetchone()[0] == 1


def test_phase5_settles_against_later_public_observations(tmp_path: Path):
    cfg = Phase5Config()
    store = DataStoreAgent(str(tmp_path / "settle.db"))
    base = time.time()
    approve(store, cfg, base - 10)
    persist_observation(store, "obs-entry", base, 100.0)
    persist_forecast(store, base, base + 300)
    lab = ShadowFlightAgent(cfg, None, store)
    assert lab.run_once(drive_upstream=False)["intents_created"] == 1
    shadow_id = store.get_phase5_shadow_intents(limit=1)[0]["shadow_intent_id"]
    with store._lock:
        store.conn.execute(
            "UPDATE phase5_shadow_intents SET target_ts=? WHERE shadow_intent_id=?",
            (base + 1, shadow_id),
        )
        store.conn.commit()
    persist_observation(store, "obs-fill", base + 1, 100.1)
    persist_observation(store, "obs-exit", base + 2, 102.0)
    settlement_result = store.settle_mature_shadow_intents(
        lab.settler,
        now_ts=base + 2,
        tolerance_sec=cfg.phase5_shadow_settlement_tolerance_sec,
    )
    assert settlement_result["settled"] == 1
    settlement = store.get_phase5_shadow_settlements(limit=1)[0]
    assert settlement["status"] == "SETTLED"
    assert settlement["fill_ratio"] == 1.0
    assert settlement["transmission_attempted"] == 0
    assert settlement["real_orders_submitted"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_parameter_drift_locks_shadow_generation(tmp_path: Path):
    cfg = Phase5Config()
    store = DataStoreAgent(str(tmp_path / "drift.db"))
    base = time.time() - 30
    freeze = approve(store, cfg, base - 10)
    assert freeze.config_hash == frozen_config_hash(cfg)
    cfg.phase2_breakout_min_expansion = 9.99
    persist_observation(store, "obs-entry", base, 100.0)
    persist_forecast(store, base, base + 300)
    payload = ShadowFlightAgent(cfg, None, store).run_once(drive_upstream=False)
    assert payload["status"] == "LOCKED"
    assert "frozen_parameter_drift" in payload["reasons"]
    assert payload["intents_created"] == 0


def test_phase5_skips_already_expired_forecasts(tmp_path: Path):
    cfg = Phase5Config()
    store = DataStoreAgent(str(tmp_path / "expired.db"))
    base = time.time() - 1000
    approve(store, cfg, base - 10)
    persist_observation(store, "obs-entry", base, 100.0)
    persist_forecast(store, base, base + 300)
    payload = ShadowFlightAgent(cfg, None, store).run_once(drive_upstream=False)
    assert payload["status"] == "SHADOW_ACTIVE"
    assert payload["intents_created"] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM phase5_shadow_intents").fetchone()[0] == 0

class CountingHypothesis:
    def __init__(self):
        self.calls = 0
    def run_once(self):
        self.calls += 1
        return {"phase": 2, "status": "HEALTHY", "forecasts": []}

class ExecutionHolder:
    def __init__(self, hypothesis):
        self.hypothesis_swarm = hypothesis

class ForbiddenValidationRerun:
    def __init__(self, hypothesis):
        self.execution_lab = ExecutionHolder(hypothesis)
    def run_once(self, drive_phase3=True):
        raise AssertionError("an approved Phase-4 court record must not be replaced during shadow flight")


def test_approved_shadow_drives_only_frozen_public_hypothesis_path(tmp_path: Path):
    cfg = Phase5Config()
    store = DataStoreAgent(str(tmp_path / "upstream.db"))
    approve(store, cfg, time.time() - 10)
    hypothesis = CountingHypothesis()
    validation = ForbiddenValidationRerun(hypothesis)
    payload = ShadowFlightAgent(cfg, validation, store).run_once(drive_upstream=True)
    assert hypothesis.calls == 1
    assert payload["status"] == "SHADOW_ACTIVE"
    assert payload["upstream_cycle"]["mode"] == "frozen_champion_public_hypothesis_only"
