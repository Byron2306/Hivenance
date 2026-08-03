from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.cost_model import ResearchCostModel
from strategies.volatility_breakout.hypothesis_models import (
    BreakoutContinuationModel,
    ExhaustionMeanReversionModel,
)
from strategies.volatility_breakout.research_model_federation import (
    FreqAITransparentLinearCandidate,
)
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition
from strategies.volatility_breakout.models import FeatureVector


@dataclass
class Phase2Config:
    exchange: str = "kraken"
    phase2_hypotheses_enabled: bool = True
    phase1_observation_interval_sec: int = 120
    phase2_horizons_seconds: tuple[int, ...] = (300, 900, 3600)
    phase2_min_data_quality: float = 0.99
    phase2_federation_enabled: bool = True
    phase2_federation_min_data_quality: float = 0.99
    phase2_federation_minimum_edge_multiple: float = 1.1
    phase2_federation_score_scale: float = 1.15
    phase2_federation_freqai_confidence_floor: float = 0.28
    phase2_taker_fee_bps_per_side: float = 10.0
    phase2_reference_notional_usd: float = 5.0
    phase2_latency_buffer_bps: float = 2.0
    phase2_safety_buffer_bps: float = 3.0
    phase2_max_total_cost_bps: float = 150.0
    phase2_minimum_edge_multiple: float = 2.0
    phase2_breakout_min_expansion: float = 1.25
    phase2_breakout_min_volume_zscore: float = 0.50
    phase2_breakout_min_return_zscore: float = 0.75
    phase2_breakout_allowed_regimes: tuple[str, ...] = ("trend_expansion", "balanced_transition")
    phase2_breakout_min_regime_confidence: float = 0.35
    phase2_breakout_min_tradability_score: float = 0.55
    phase2_breakout_min_momentum_consistency: float = 0.55
    phase2_require_frontier_for_adaptive_recovery: bool = True
    phase2_frontier_min_realized_net_bps: float = 2.5
    phase2_frontier_min_samples: int = 5
    phase2_regime_suppression_min_samples: int = 6
    phase2_regime_suppression_max_mean_net_bps: float = -2.5
    phase2_regime_reentry_recent_window: int = 6
    phase2_regime_reentry_min_samples: int = 3
    phase2_regime_reentry_min_mean_net_bps: float = 2.0
    phase2_reversion_min_stretch_zscore: float = 1.50
    phase2_reversion_min_range_extreme: float = 0.85
    phase2_reversion_allowed_regimes: tuple[str, ...] = ("stretch_exhaustion", "quiet_range", "balanced_transition")
    phase2_reversion_min_regime_confidence: float = 0.30
    phase2_reversion_min_tradability_score: float = 0.50
    phase2_reversion_min_reversal_strength: float = 0.30


def feature(**overrides) -> FeatureVector:
    values = dict(
        symbol="TEST/USD",
        timestamp_ms=int(time.time() * 1000),
        price=100.0,
        realized_volatility_fast=0.008,
        realized_volatility_baseline=0.004,
        volatility_expansion=2.0,
        volume_zscore=2.0,
        trade_count_zscore=None,
        order_flow_imbalance=None,
        book_imbalance=0.25,
        spread_bps=4.0,
        depth_usd_25bps=1_000_000.0,
        quote_volume_24h=100_000_000.0,
        return_5=0.012,
        freshness_sec=1.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.72},
        },
        complete=True,
        return_zscore=2.2,
        price_zscore=2.0,
        range_position=0.95,
        trend_slope=0.001,
        atr_pct=0.01,
        reversal_return_1=0.003,
        momentum_consistency=0.8,
        volume_ratio=2.0,
    )
    values.update(overrides)
    return FeatureVector(**values)


def test_breakout_continuation_produces_cost_adjusted_forecast():
    model = BreakoutContinuationModel(ResearchCostModel())
    forecast = model.forecast(feature())
    assert forecast.abstain is False
    assert forecast.direction == "UP"
    assert forecast.expected_net_bps > 0
    assert forecast.expected_move_bps > forecast.expected_cost_bps
    assert forecast.execution_eligible is False
    assert forecast.calibration_state == "COLD_START_PROVISIONAL"


def test_breakout_continuation_rejects_hostile_regime():
    model = BreakoutContinuationModel(ResearchCostModel())
    forecast = model.forecast(feature(values={
        "feature_version": "phase2.v1",
        "regime_inputs": {"regime_hint": "quiet_range", "confidence": 0.80},
    }))
    assert forecast.abstain is True
    assert "breakout_regime_mismatch" in forecast.reasons


def test_breakout_continuation_rejects_exciting_but_untradable_setup():
    model = BreakoutContinuationModel(ResearchCostModel())
    forecast = model.forecast(
        feature(
            spread_bps=18.0,
            depth_usd_25bps=120_000.0,
            quote_volume_24h=3_000_000.0,
            volume_zscore=0.8,
            momentum_consistency=0.85,
            return_zscore=2.4,
            volatility_expansion=1.8,
        )
    )
    assert forecast.abstain is True
    assert "breakout_tradability_too_low" in forecast.reasons
    assert forecast.inputs["tradability"]["tradability_score"] < 0.55


def test_breakout_continuation_requires_persistent_momentum():
    model = BreakoutContinuationModel(ResearchCostModel())
    forecast = model.forecast(feature(momentum_consistency=0.18, book_imbalance=0.05))
    assert forecast.abstain is True
    assert "momentum_not_persistent" in forecast.reasons


def test_mean_reversion_requires_exhaustion_confirmation():
    model = ExhaustionMeanReversionModel(ResearchCostModel())
    reversion_values = {
        "feature_version": "phase2.v1",
        "regime_inputs": {"regime_hint": "stretch_exhaustion", "confidence": 0.82},
    }
    no_reversal = model.forecast(feature(reversal_return_1=0.004, book_imbalance=0.2, values=reversion_values))
    assert no_reversal.abstain is True
    assert "exhaustion_not_confirmed" in no_reversal.reasons

    confirmed = model.forecast(feature(reversal_return_1=-0.005, book_imbalance=-0.2, values=reversion_values))
    assert confirmed.abstain is False
    assert confirmed.direction == "DOWN"
    assert confirmed.execution_eligible is False


def test_mean_reversion_rejects_wrong_regime_even_with_reversal():
    model = ExhaustionMeanReversionModel(ResearchCostModel())
    forecast = model.forecast(
        feature(
            reversal_return_1=-0.005,
            book_imbalance=-0.2,
            return_zscore=2.0,
            range_position=0.95,
            values={
                "feature_version": "phase2.v1",
                "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.90},
            },
        )
    )
    assert forecast.abstain is True
    assert "reversion_regime_mismatch" in forecast.reasons


def test_mean_reversion_rejects_weak_reversal_even_if_direction_flips():
    model = ExhaustionMeanReversionModel(ResearchCostModel())
    forecast = model.forecast(
        feature(
            reversal_return_1=-0.0003,
            book_imbalance=-0.08,
            return_zscore=2.1,
            range_position=0.96,
            values={
                "feature_version": "phase2.v1",
                "regime_inputs": {"regime_hint": "stretch_exhaustion", "confidence": 0.90},
            },
        )
    )
    assert forecast.abstain is True
    assert "reversal_strength_too_low" in forecast.reasons


def test_mean_reversion_rejects_untradable_exhaustion():
    model = ExhaustionMeanReversionModel(ResearchCostModel())
    forecast = model.forecast(
        feature(
            reversal_return_1=-0.006,
            book_imbalance=-0.25,
            return_zscore=2.4,
            range_position=0.97,
            spread_bps=16.0,
            depth_usd_25bps=90_000.0,
            quote_volume_24h=2_500_000.0,
            values={
                "feature_version": "phase2.v1",
                "regime_inputs": {"regime_hint": "stretch_exhaustion", "confidence": 0.88},
            },
        )
    )
    assert forecast.abstain is True
    assert "reversion_tradability_too_low" in forecast.reasons


def test_freqai_candidate_tuning_can_convert_borderline_signal_into_research_forecast():
    cost = ResearchCostModel()
    baseline = FreqAITransparentLinearCandidate(cost)
    tuned = FreqAITransparentLinearCandidate(
        cost,
        minimum_edge_multiple=1.1,
        score_scale=1.15,
        confidence_floor=0.28,
    )
    borderline = feature(
        return_zscore=0.32,
        trend_slope=0.00004,
        book_imbalance=0.03,
        volume_zscore=0.18,
        range_position=0.59,
        volatility_expansion=1.08,
        atr_pct=0.012,
        return_5=0.0015,
    )
    cold = baseline.forecast(borderline)
    warmer = tuned.forecast(borderline)
    assert cold.abstain is True
    assert "linear_candidate_confidence_low" in cold.reasons
    assert warmer.abstain is False
    assert warmer.expected_net_bps is not None and warmer.expected_net_bps > 0
    assert warmer.execution_eligible is False


def test_hypothesis_competition_uses_cohort_specific_model_roster():
    cfg = Phase2Config()
    comp = HypothesisCompetition(cfg)
    mean_rev_feature = feature(
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "stretch_exhaustion", "confidence": 0.82},
            "cohort_bucket": "mean_reversion",
        },
        reversal_return_1=-0.005,
        book_imbalance=-0.2,
        return_zscore=2.0,
        range_position=0.95,
    )
    rows = comp.evaluate(mean_rev_feature, [300])
    model_ids = {row.model_id for row in rows}
    assert "exhaustion_mean_reversion_v1" in model_ids
    assert "adapter_freqtrade_breakout_v1" not in model_ids
    assert "baseline_simple_momentum_v1" in model_ids


def test_hypothesis_competition_recovers_borderline_event_driven_breakout():
    cfg = Phase2Config()
    comp = HypothesisCompetition(cfg)
    borderline = feature(
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.72},
            "cohort_bucket": "event_driven",
            "tradable_opportunity_score": 0.72,
            "research_richness_score": 0.55,
            "phase2_profitability_frontier": {
                "breakout": {"eligible": True, "mean_realized_net_bps": 6.5, "settled_trades": 8},
            },
        },
        volatility_expansion=1.17,
        volume_zscore=1.1,
        return_zscore=0.69,
        momentum_consistency=0.53,
        return_5=0.007,
        trend_slope=0.001,
        book_imbalance=0.20,
    )
    rows = [row for row in comp.evaluate(borderline, [300]) if row.model_id == "breakout_continuation_v1"]
    assert rows
    forecast = rows[0]
    assert forecast.abstain is False
    assert forecast.expected_net_bps is not None and forecast.expected_net_bps > 0
    assert forecast.inputs["adaptive_policy"]["adaptation_reason"] == "event_driven_high_tradable_opportunity"
    assert forecast.inputs["adaptive_policy"]["recovery_mode"] == "borderline_regime_confirmed"


def test_hypothesis_competition_recovers_borderline_mean_reversion_setup():
    cfg = Phase2Config()
    comp = HypothesisCompetition(cfg)
    borderline = feature(
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "stretch_exhaustion", "confidence": 0.84},
            "cohort_bucket": "mean_reversion",
            "tradable_opportunity_score": 0.54,
            "research_richness_score": 0.74,
            "phase2_profitability_frontier": {
                "reversion": {"eligible": True, "mean_realized_net_bps": 5.5, "settled_trades": 8},
            },
        },
        return_zscore=1.38,
        range_position=0.82,
        reversal_return_1=-0.0027,
        book_imbalance=-0.12,
        volatility_expansion=1.25,
        return_5=0.011,
    )
    rows = [row for row in comp.evaluate(borderline, [300]) if row.model_id == "exhaustion_mean_reversion_v1"]
    assert rows
    forecast = rows[0]
    assert forecast.abstain is False
    assert forecast.expected_net_bps is not None and forecast.expected_net_bps > 0
    assert forecast.inputs["adaptive_policy"]["adaptation_reason"] == "mean_reversion_high_research_value"
    assert forecast.inputs["adaptive_policy"]["recovery_mode"] == "borderline_regime_confirmed"


def test_hypothesis_competition_does_not_recover_breakout_without_regime_confirmation():
    cfg = Phase2Config()
    comp = HypothesisCompetition(cfg)
    borderline = feature(
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.42},
            "cohort_bucket": "event_driven",
            "tradable_opportunity_score": 0.78,
            "research_richness_score": 0.55,
            "phase2_profitability_frontier": {
                "breakout": {"eligible": True, "mean_realized_net_bps": 6.5, "settled_trades": 8},
            },
        },
        volatility_expansion=1.17,
        volume_zscore=1.1,
        return_zscore=0.69,
        momentum_consistency=0.53,
        return_5=0.007,
        trend_slope=0.001,
        book_imbalance=0.20,
    )
    rows = [row for row in comp.evaluate(borderline, [300]) if row.model_id == "breakout_continuation_v1"]
    assert rows
    forecast = rows[0]
    assert forecast.abstain is True


def test_hypothesis_competition_does_not_recover_reversion_in_wrong_regime():
    cfg = Phase2Config()
    comp = HypothesisCompetition(cfg)
    borderline = feature(
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.84},
            "cohort_bucket": "mean_reversion",
            "tradable_opportunity_score": 0.54,
            "research_richness_score": 0.74,
            "phase2_profitability_frontier": {
                "reversion": {"eligible": True, "mean_realized_net_bps": 5.5, "settled_trades": 8},
            },
        },
        return_zscore=1.38,
        range_position=0.82,
        reversal_return_1=-0.0027,
        book_imbalance=-0.12,
        volatility_expansion=1.25,
        return_5=0.011,
    )
    rows = [row for row in comp.evaluate(borderline, [300]) if row.model_id == "exhaustion_mean_reversion_v1"]
    assert rows
    forecast = rows[0]
    assert forecast.abstain is True


def test_hypothesis_competition_does_not_recover_without_frontier_support():
    cfg = Phase2Config()
    comp = HypothesisCompetition(cfg)
    borderline = feature(
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.72},
            "cohort_bucket": "event_driven",
            "tradable_opportunity_score": 0.72,
            "research_richness_score": 0.55,
        },
        volatility_expansion=1.17,
        volume_zscore=1.1,
        return_zscore=0.69,
        momentum_consistency=0.53,
        return_5=0.007,
        trend_slope=0.001,
        book_imbalance=0.20,
    )
    rows = [row for row in comp.evaluate(borderline, [300]) if row.model_id == "breakout_continuation_v1"]
    assert rows
    forecast = rows[0]
    assert forecast.abstain is True


def test_hypothesis_competition_suppresses_negative_regime_memory_models():
    cfg = Phase2Config()
    comp = HypothesisCompetition(cfg)
    stressed = feature(
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.82},
            "cohort_bucket": "event_driven",
            "tradable_opportunity_score": 0.72,
            "research_richness_score": 0.55,
            "phase2_profitability_frontier": {
                "breakout": {"eligible": True, "mean_realized_net_bps": 6.5, "settled_trades": 8},
            },
            "phase2_regime_suppression": {
                "trend_expansion": {
                    "breakout_continuation_v1": {
                        "suppressed": True,
                        "mean_realized_net_bps": -6.0,
                        "settled_trades": 12,
                    }
                }
            },
        },
        volatility_expansion=1.30,
        volume_zscore=1.4,
        return_zscore=1.2,
        momentum_consistency=0.70,
        return_5=0.009,
        trend_slope=0.001,
        book_imbalance=0.20,
    )
    rows = comp.evaluate(stressed, [300])
    model_ids = {row.model_id for row in rows}
    assert "breakout_continuation_v1" not in model_ids
    assert "exhaustion_mean_reversion_v1" not in model_ids
    assert "baseline_simple_momentum_v1" in model_ids


def test_hypothesis_swarm_releases_suppression_after_fresh_positive_regime_evidence(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase2_regime_reentry.db"))
    now = time.time()
    model_id = "candidate_freqai_transparent_linear_v1"
    hypothesis = "breakout_continuation"
    regime_hint = "quiet_range"

    def seed(index: int, realized_net_bps: float, minutes_ago: int) -> None:
        fid = f"reentry-{index}"
        ts = now - minutes_ago * 60
        payload = json.dumps({
            "forecast_id": fid,
            "model_id": model_id,
            "hypothesis": hypothesis,
            "symbol": "BTC/USD",
            "abstain": False,
            "expected_net_bps": max(1.0, realized_net_bps + 3.0),
            "inputs": {
                "regime_inputs": {"regime_hint": regime_hint},
                "regime_hint": regime_hint,
                "cohort_bucket": "research_bench",
                "symbol_class": "majors",
            },
        })
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
                fid, "run", f"obs-{fid}", ts, ts + 300, "kraken", "BTC/USD", model_id,
                hypothesis, 300, "UP", 100.0, 0.6, 12.0, 4.0, max(1.0, realized_net_bps + 3.0), 0.7,
                0, "test", 1, 0, payload,
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
                fid, ts + 310, 101.0, realized_net_bps, realized_net_bps, realized_net_bps,
                1 if realized_net_bps > 0 else 0, 0.1, 5.0, "{}",
            ),
        )

    for index, realized in enumerate((-12.0, -11.0, -10.0, -9.0, 5.0, 6.0, 7.0), start=1):
        seed(index, realized, minutes_ago=20 - index)
    store.conn.commit()

    cfg = Phase2Config(phase2_regime_reentry_recent_window=3)
    swarm = HypothesisSwarmAgent(cfg, StubObserver(feature()), coordinator=StoreBridge(store))
    suppression = swarm._regime_suppression_map()
    quiet_range = suppression.get(regime_hint) or {}
    payload = quiet_range.get(model_id) or {}

    assert payload
    assert payload["suppressed"] is False
    assert payload["released"] is True
    assert payload["reason"] == "fresh_positive_regime_reentry"
    assert payload["recent_sample_count"] >= 3
    assert float(payload["recent_mean_realized_net_bps"]) >= 2.0


def test_scorecard_exposes_cohort_breakdown(tmp_path: Path):
    now_ms = int(time.time() * 1000)
    vector = feature(
        timestamp_ms=now_ms - 400_000,
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "stretch_exhaustion", "confidence": 0.82},
            "cohort_bucket": "mean_reversion",
        },
    )
    store = DataStoreAgent(str(tmp_path / "phase2_cohort.db"))
    bridge = StoreBridge(store)
    observer = StubObserver(vector)
    swarm = HypothesisSwarmAgent(Phase2Config(), observer, coordinator=bridge)
    swarm.run_once()
    future_ts = (vector.timestamp_ms + 310_000)
    store.handle_event({
        "buzz": {"type": "buzz.observation.snapshot", "source": "TEST", "ts": future_ts},
        "payload": {
            "status": "HEALTHY",
            "dataset_hash": "future-hash",
            "run": {
                "run_id": "obs-future",
                "started_at_ms": future_ts,
                "completed_at_ms": future_ts,
                "venue": "kraken",
                "symbols_attempted": 1,
                "symbols_successful": 1,
                "symbols_eligible": 1,
                "mean_data_quality": 1.0,
                "errors": [],
            },
            "candidates": [{
                "symbol": vector.symbol,
                "venue": "kraken",
                "timestamp_ms": future_ts,
                "price": 101.5,
                "data_quality": 1.0,
                "observation_eligible": True,
                "execution_eligible": False,
                "rejection_reasons": [],
                "values": {"volatility_expansion": 1.5},
            }],
        },
    })
    store.settle_mature_hypothesis_forecasts(now_ts=time.time(), tolerance_sec=120)
    scorecard = store.get_hypothesis_scorecard()
    assert "cohort_breakdown" in scorecard
    assert "mean_reversion" in scorecard["cohort_breakdown"]
    assert "abstention_reason_breakdown" in scorecard
    assert "near_miss_recovery_candidates" in scorecard
    assert "slice_breakdown" in scorecard
    assert "regime_model_breakdown" in scorecard
    assert "profitability_frontier" in scorecard
    assert any(row.get("symbol_class") for row in scorecard["slice_breakdown"])


def test_scorecard_exposes_abstention_pressure_and_recovery_candidates(tmp_path: Path):
    now_ms = int(time.time() * 1000)
    vector = feature(
        timestamp_ms=now_ms - 400_000,
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "balanced_transition", "confidence": 0.78},
            "cohort_bucket": "event_driven",
        },
        volatility_expansion=1.18,
        volume_zscore=1.4,
        return_zscore=1.55,
        momentum_consistency=0.72,
        trend_slope=0.0007,
        return_5=0.007,
        book_imbalance=0.18,
        spread_bps=4.5,
        depth_usd_25bps=900_000.0,
    )
    store = DataStoreAgent(str(tmp_path / "phase2_recovery.db"))
    bridge = StoreBridge(store)
    observer = StubObserver(vector)
    swarm = HypothesisSwarmAgent(Phase2Config(), observer, coordinator=bridge)
    swarm.run_once()

    scorecard = store.get_hypothesis_scorecard()
    reasons = scorecard.get("abstention_reason_breakdown") or []
    recovery = scorecard.get("near_miss_recovery_candidates") or []

    assert reasons
    assert any(row.get("reason") == "volatility_not_expanding" for row in reasons)
    assert recovery
    assert any(row.get("symbol") == vector.symbol for row in recovery)
    assert any(row.get("near_miss_score", 0) >= 0.72 for row in recovery)


class StubObserver:
    def __init__(self, vector: FeatureVector) -> None:
        self.vector = vector
        self.orders = []

    def run_once(self):
        return {
            "phase": 1,
            "status": "HEALTHY",
            "dataset_hash": "observation-hash",
            "run": {
                "run_id": "obs-test",
                "venue": "kraken",
                "started_at_ms": self.vector.timestamp_ms,
                "completed_at_ms": self.vector.timestamp_ms,
            },
            "candidates": [
                {
                    "symbol": self.vector.symbol,
                    "venue": "kraken",
                    "timestamp_ms": self.vector.timestamp_ms,
                    "price": self.vector.price,
                    "values": {"feature_vector": asdict(self.vector)},
                }
            ],
        }


class StoreBridge:
    def __init__(self, store: DataStoreAgent) -> None:
        self.store = store
        self.events = []

    def share_data(self, key, event):
        self.events.append((key, event))
        self.store.handle_event(event)


def test_hypothesis_swarm_persists_competition_and_never_executes(tmp_path: Path):
    now_ms = int(time.time() * 1000)
    vector = feature(timestamp_ms=now_ms - 400_000)
    store = DataStoreAgent(str(tmp_path / "phase2.db"))
    bridge = StoreBridge(store)
    observer = StubObserver(vector)
    swarm = HypothesisSwarmAgent(Phase2Config(), observer, coordinator=bridge)

    payload = swarm.run_once()
    assert payload["mode"] == "hypothesis_research_only"
    assert payload["execution_wired"] is False
    assert payload["orders_submitted"] == 0
    assert len(payload["forecasts"]) == 36
    assert all(row["execution_eligible"] is False for row in payload["forecasts"])
    assert all(row["order_intent"] is None for row in payload["forecasts"])
    assert observer.orders == []

    future_ts = (vector.timestamp_ms + 310_000)
    store.handle_event({
        "buzz": {"type": "buzz.observation.snapshot", "source": "TEST", "ts": future_ts},
        "payload": {
            "status": "HEALTHY",
            "dataset_hash": "future-hash",
            "run": {
                "run_id": "obs-future",
                "started_at_ms": future_ts,
                "completed_at_ms": future_ts,
                "venue": "kraken",
                "symbols_attempted": 1,
                "symbols_successful": 1,
                "symbols_eligible": 1,
                "mean_data_quality": 1.0,
                "errors": [],
            },
            "candidates": [{
                "symbol": vector.symbol,
                "venue": "kraken",
                "timestamp_ms": future_ts,
                "price": 101.5,
                "data_quality": 1.0,
                "observation_eligible": True,
                "execution_eligible": False,
                "rejection_reasons": [],
                "values": {"volatility_expansion": 1.5},
            }],
        },
    })

    settlement = store.settle_mature_hypothesis_forecasts(now_ts=time.time(), tolerance_sec=120)
    assert settlement["settled"] == 12  # twelve models at the five-minute horizon
    assert settlement["orders_submitted"] == 0
    outcomes = store.get_hypothesis_outcomes(limit=50)
    assert len(outcomes) == 12
    scorecard = store.get_hypothesis_scorecard()
    assert len(scorecard["models"]) == 12
    assert scorecard["execution_eligible"] is False
    assert "demotion_recommendations" in scorecard
    assert "expectancy_breakdown" in scorecard

    readiness = store.get_phase2_readiness(min_forecasts=1, min_settled_non_abstain=1, min_distinct_days=1)
    assert readiness["execution_eligible"] is False
    assert readiness["orders_submitted"] == 0


def test_low_quality_features_force_both_primary_models_to_abstain():
    cost = ResearchCostModel()
    bad = feature(data_quality=0.5, complete=False)
    assert BreakoutContinuationModel(cost).forecast(bad).abstain is True
    assert ExhaustionMeanReversionModel(cost).forecast(bad).abstain is True


def test_scorecard_flags_active_negative_model_for_demotion(tmp_path: Path):
    now_ms = int(time.time() * 1000)
    vector = feature(timestamp_ms=now_ms - 400_000)
    store = DataStoreAgent(str(tmp_path / "phase2_demote.db"))
    bridge = StoreBridge(store)
    observer = StubObserver(vector)
    swarm = HypothesisSwarmAgent(Phase2Config(), observer, coordinator=bridge)
    payload = swarm.run_once()

    target_model = "candidate_freqai_transparent_linear_v1"
    for index in range(30):
        forecast = next(row for row in payload["forecasts"] if row["model_id"] == target_model and row["horizon_seconds"] == 300 and not row["abstain"])
        forecast_id = f"{forecast['forecast_id']}-{index}"
        entry_price = 100.0
        exit_price = 99.4
        market_return_bps = ((exit_price - entry_price) / entry_price) * 10_000.0
        net_bps = market_return_bps - float(forecast.get("expected_cost_bps") or 0.0)
        store.conn.execute(
            "INSERT OR REPLACE INTO hypothesis_forecasts (forecast_id, run_id, observation_run_id, ts, target_ts, venue, symbol, model_id, hypothesis, horizon_seconds, direction, entry_price, probability_positive_net, expected_move_bps, expected_cost_bps, expected_net_bps, raw_score, abstain, reason, settled, execution_eligible, payload) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                forecast_id, forecast["run_id"], forecast["observation_run_id"], forecast["timestamp_ms"] / 1000.0,
                forecast["target_timestamp_ms"] / 1000.0, forecast["venue"], forecast["symbol"], forecast["model_id"],
                forecast["hypothesis"], forecast["horizon_seconds"], forecast["direction"], entry_price, forecast["probability_positive_net"],
                forecast["expected_move_bps"], forecast["expected_cost_bps"], forecast["expected_net_bps"], forecast["raw_score"],
                0, forecast["reason"], 1, 0, "{}",
            ),
        )
        store.conn.execute(
            "INSERT OR REPLACE INTO hypothesis_outcomes (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps, net_return_bps, positive_net, brier_score, absolute_error_bps, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                forecast_id, time.time(), exit_price, market_return_bps, market_return_bps, net_bps, 0, 0.25, 10.0,
                '{"model_id":"candidate_freqai_transparent_linear_v1","realized_net_bps":%s}' % net_bps,
            ),
        )
    store.conn.commit()
    scorecard = store.get_hypothesis_scorecard()
    flagged = [row for row in scorecard.get("demotion_recommendations", []) if row.get("model_id") == target_model]
    assert flagged


def test_expectancy_breakdown_is_weighted_by_sample_count(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase2_weighted.db"))
    rows = [
        {
            "forecast_id": "small-good",
            "model_id": "breakout_continuation_v1",
            "hypothesis": "breakout_continuation",
            "symbol": "ETH/USD",
            "expected_net_bps": 100.0,
            "net_return_bps": 100.0,
            "count": 1,
        },
        {
            "forecast_id": "large-weak",
            "model_id": "exhaustion_mean_reversion_v1",
            "hypothesis": "exhaustion_mean_reversion",
            "symbol": "BTC/USD",
            "expected_net_bps": 10.0,
            "net_return_bps": 10.0,
            "count": 9,
        },
    ]
    now = time.time()
    for row in rows:
        for index in range(row["count"]):
            forecast_id = f"{row['forecast_id']}-{index}"
            ts = now - (index + 1) * 60
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
                    forecast_id, "run", f"obs-{forecast_id}", ts, ts + 300, "kraken", row["symbol"], row["model_id"],
                    row["hypothesis"], 300, "UP", 100.0, 0.6, row["expected_net_bps"] + 20.0, 20.0,
                    row["expected_net_bps"], 0.7, 0, "test", 1, 0, "{}",
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
                    forecast_id, ts + 310, 101.0, row["net_return_bps"], row["net_return_bps"],
                    row["net_return_bps"], 1, 0.1, 5.0, "{}",
                ),
            )
    store.conn.commit()

    scorecard = store.get_hypothesis_scorecard()
    native = scorecard["expectancy_breakdown"]["native"]

    assert native["settled_trades"] == 10
    assert native["mean_realized_net_bps"] == 19.0
    assert native["mean_expected_net_bps"] == 19.0


def test_profitability_frontier_exposes_positive_model_regime_slices(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase2_frontier.db"))
    now = time.time()

    def seed(
        *,
        forecast_id: str,
        model_id: str,
        hypothesis: str,
        regime_hint: str,
        expected_net_bps: float,
        realized_net_bps: float,
        count: int,
    ) -> None:
        for index in range(count):
            fid = f"{forecast_id}-{index}"
            ts = now - (index + 1) * 60
            payload = json.dumps({
                "forecast_id": fid,
                "model_id": model_id,
                "hypothesis": hypothesis,
                "symbol": "ETH/USD" if "trend" in regime_hint else "BTC/USD",
                "abstain": False,
                "expected_net_bps": expected_net_bps,
                "inputs": {
                    "regime_inputs": {"regime_hint": regime_hint},
                    "regime_hint": regime_hint,
                    "cohort_bucket": "breakout" if hypothesis == "breakout_continuation" else "mean_reversion",
                    "symbol_class": "majors",
                },
            })
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
                    fid, "run", f"obs-{fid}", ts, ts + 300, "kraken",
                    "ETH/USD" if "trend" in regime_hint else "BTC/USD",
                    model_id, hypothesis, 300, "UP", 100.0, 0.62,
                    expected_net_bps + 20.0, 20.0, expected_net_bps, 0.7, 0,
                    "test", 1, 0, payload,
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
                    fid, ts + 310, 101.0, realized_net_bps, realized_net_bps,
                    realized_net_bps, 1 if realized_net_bps > 0 else 0, 0.1, 5.0, "{}",
                ),
            )

    seed(
        forecast_id="freqai-trend",
        model_id="candidate_freqai_transparent_linear_v1",
        hypothesis="breakout_continuation",
        regime_hint="trend_expansion",
        expected_net_bps=7.5,
        realized_net_bps=9.0,
        count=12,
    )
    seed(
        forecast_id="freqai-range",
        model_id="candidate_freqai_transparent_linear_v1",
        hypothesis="breakout_continuation",
        regime_hint="quiet_range",
        expected_net_bps=6.0,
        realized_net_bps=-4.0,
        count=12,
    )
    store.conn.commit()

    scorecard = store.get_hypothesis_scorecard()
    regime_rows = scorecard.get("regime_model_breakdown") or []
    frontier = scorecard.get("profitability_frontier") or []

    assert any(
        row.get("model_id") == "candidate_freqai_transparent_linear_v1"
        and row.get("regime_hint") == "trend_expansion"
        and float(row.get("mean_realized_net_bps") or 0.0) > 0
        for row in regime_rows
    )
    assert any(
        row.get("model_id") == "candidate_freqai_transparent_linear_v1"
        and row.get("regime_hint") == "trend_expansion"
        and row.get("promotion_hint") == "credible_positive_slice"
        for row in frontier
    )
    assert not any(
        row.get("model_id") == "candidate_freqai_transparent_linear_v1"
        and row.get("regime_hint") == "quiet_range"
        for row in frontier
    )
