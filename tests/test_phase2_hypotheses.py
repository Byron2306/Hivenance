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
    CexMultiHorizonMarketOracle,
    FreqAITransparentLinearCandidate,
    ResearchModelFederation,
    TriunePolyphonicSynthesisCandidate,
)
from strategies.volatility_breakout.worker_coalition_model import WorkerCoalitionMetaModel
from strategies.volatility_breakout.worker_signal_federation import WorkerSignalFederation, WorkerSignalModel
from strategies.volatility_breakout.hypothesis_swarm import CommonsPhase2Governor, HypothesisSwarmAgent
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
    phase2_worker_signal_federation_enabled: bool = True
    phase2_worker_signal_models: tuple[str, ...] = (
        "worker_signal_sma_v1",
        "worker_signal_rsi_v1",
        "worker_signal_rsi2_v1",
        "worker_signal_breakout_v1",
        "worker_signal_momentum_v1",
        "worker_signal_bollinger_v1",
        "worker_signal_supertrend_v1",
        "worker_signal_vol_expansion_v1",
    )
    phase2_worker_signal_min_data_quality: float = 0.99
    phase2_worker_signal_minimum_edge_multiple: float = 1.1
    phase2_worker_signal_min_strength: float = 0.45
    phase2_worker_signal_score_scale: float = 1.0
    phase2_worker_signal_settle_counterfactuals_enabled: bool = True
    phase2_worker_coalition_enabled: bool = True
    phase2_worker_coalition_models: tuple[str, ...] = (
        "worker_signal_sma_v1",
        "worker_signal_rsi_v1",
        "worker_signal_rsi2_v1",
        "worker_signal_breakout_v1",
        "worker_signal_momentum_v1",
        "worker_signal_bollinger_v1",
        "worker_signal_supertrend_v1",
        "worker_signal_vol_expansion_v1",
    )
    phase2_worker_coalition_min_voters: int = 2
    phase2_worker_coalition_min_agreement: float = 0.58
    phase2_worker_coalition_min_strength: float = 0.45
    phase2_worker_coalition_minimum_edge_multiple: float = 1.2
    phase2_worker_coalition_settle_counterfactuals_enabled: bool = True
    phase2_worker_coalition_challenged_vote_weight: float = 0.55
    phase2_meta_strategy_council_enabled: bool = True
    phase2_meta_strategy_min_harmony_index: float = 0.60
    phase2_meta_strategy_min_regime_confidence: float = 0.35
    phase2_meta_strategy_stale_after_sec: float = 45.0
    phase2_meta_strategy_min_continuity: float = 0.92
    phase2_meta_strategy_negative_memory_mean_net_bps: float = -5.0
    phase2_meta_strategy_negative_memory_min_samples: int = 3
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


class NoopObserver:
    pass


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


def test_default_phase2_horizon_floor_stays_conservative():
    cfg = Phase2Config()
    cfg.phase2_horizons_seconds = (30, 60)

    swarm = HypothesisSwarmAgent(cfg, NoopObserver())

    assert swarm.horizons == (60,)


def test_high_vol_profile_can_unlock_subminute_phase2_horizons():
    cfg = Phase2Config()
    cfg.profile_name = "high_vol_low_stakes"
    cfg.phase2_horizons_seconds = (30, 60, 300)
    cfg.phase2_min_horizon_seconds = 10
    cfg.phase2_interval_sec = 10
    cfg.phase2_min_interval_sec = 1

    swarm = HypothesisSwarmAgent(cfg, NoopObserver())

    assert swarm.horizons == (30, 60, 300)
    assert swarm.interval_sec == 10


def test_niche_research_cohort_uses_active_high_vol_model_lane():
    cfg = Phase2Config()
    competition = HypothesisCompetition(cfg)
    candidate = feature(values={
        "feature_version": "phase2.v1",
        "cohort_bucket": "niche_research",
        "symbol_class": "niche_high_volatility",
        "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.72},
    })

    model_ids = {model.model_id for model in competition._active_models_for(candidate)}

    assert "adapter_freqtrade_breakout_v1" in model_ids
    assert "worker_signal_vol_expansion_v1" in model_ids
    assert "baseline_no_trade_v1" in model_ids


def oracle_context(*, change_1h: float = 160.0, change_5h: float = 120.0, change_24h: float = 80.0) -> dict:
    return {
        "schema": "cex_market_oracle_context_v1",
        "source": "phase1_observation_snapshots",
        "symbol": "TEST/USD",
        "venue": "kraken",
        "available_horizons": 3,
        "latest": {
            "price": 101.6,
            "spread_bps": 3.0,
            "depth_usd_25bps": 1_500_000.0,
            "quote_volume_24h": 120_000_000.0,
            "data_quality": 1.0,
            "observation_eligible": True,
        },
        "horizons": {
            "1h": {"available": True, "seconds": 3600, "change_bps": change_1h},
            "5h": {"available": True, "seconds": 18_000, "change_bps": change_5h},
            "24h": {"available": True, "seconds": 86_400, "change_bps": change_24h},
            "7d": {"available": False, "reason": "insufficient_history"},
            "30d": {"available": False, "reason": "insufficient_history"},
        },
        "stability": {
            "sample_count": 32,
            "spread_mean_bps": 3.1,
            "spread_max_bps": 5.0,
            "spread_stability_ratio": 1.61,
            "depth_min_usd_25bps": 900_000.0,
            "data_quality_mean": 1.0,
        },
        "authority": "research_context_only",
        "execution_eligible": False,
        "orders_submitted": 0,
    }


def worker_series(closes: list[float] | None = None) -> dict:
    rows = closes or [100.0 + index * 0.04 for index in range(75)]
    rows[-1] = max(rows[:-1]) * 1.012
    return {
        "schema": "hivenance_worker_input_series_v1",
        "source": "phase1_ohlcv",
        "timeframe": "1m",
        "points": len(rows),
        "closes": rows,
        "volumes": [1000.0 + index * 3.0 for index in range(len(rows))],
        "latest_price": rows[-1],
        "latest_candle_ts": int(time.time() * 1000),
        "authority": "research_input_only",
        "execution_eligible": False,
        "orders_submitted": 0,
    }


def test_research_federation_excludes_quarantined_models_from_active_manifest():
    cfg = Phase2Config()
    cfg.phase2_federation_models = ("candidate_freqai_transparent_linear_v1",)
    cfg.phase2_federation_quarantined_models = {
        "candidate_freqai_transparent_linear_v1": "negative_outcome_blind_expansion"
    }
    federation = ResearchModelFederation(cfg, ResearchCostModel())

    assert federation.model_ids == ()
    assert federation.manifest()["quarantined_models"] == {
        "candidate_freqai_transparent_linear_v1": "negative_outcome_blind_expansion"
    }


def test_advanced_systems_candidate_emits_governed_tamper_evident_receipt():
    model = TriunePolyphonicSynthesisCandidate(
        ResearchCostModel(),
        minimum_edge_multiple=1.1,
        score_scale=1.15,
    )

    forecast = model.forecast(feature(), horizon_seconds=900)

    assert forecast.abstain is False
    receipt = forecast.inputs["advanced_systems_synthesis"]
    assert receipt["mandos_ledger"]["decision"] == "ACCEPT_RESEARCH_PROPOSAL"
    assert receipt["mandos_ledger"]["authority_ceiling"] == "research_proposal_only"
    assert len(receipt["mandos_ledger"]["chain"]) == 7
    assert receipt["polyphonic_resonance"]["dissent_preserved"] is True
    assert {row["system"] for row in receipt["source_manifest"]["systems"]} == {
        "vns", "cce", "triune", "polyphonic_resonance", "seraph", "sophia", "mandos"
    }
    assert receipt["execution_eligible"] is False
    assert receipt["orders_submitted"] == 0


def test_advanced_systems_candidate_refuses_cross_feature_dissonance():
    model = TriunePolyphonicSynthesisCandidate(ResearchCostModel(), minimum_edge_multiple=1.1)
    discordant = feature(
        return_5=0.009,
        return_zscore=2.0,
        trend_slope=-0.001,
        book_imbalance=1.0,
        order_flow_imbalance=1.0,
        range_position=0.0,
        price_zscore=0.0,
        momentum_consistency=0.25,
    )

    forecast = model.forecast(discordant, horizon_seconds=900)

    assert forecast.abstain is True
    receipt = forecast.inputs["advanced_systems_synthesis"]
    assert receipt["mandos_ledger"]["decision"] == "REFUSE_RESEARCH_PROPOSAL"
    assert receipt["mandos_ledger"]["refusal_reasons"]


def test_cex_multi_horizon_oracle_emits_research_forecast_from_phase1_context():
    model = CexMultiHorizonMarketOracle(
        ResearchCostModel(),
        minimum_edge_multiple=1.1,
        score_scale=1.15,
    )
    forecast = model.forecast(
        feature(values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.78},
            "cex_market_oracle": oracle_context(),
        }),
        horizon_seconds=900,
    )

    assert forecast.abstain is False
    assert forecast.direction == "UP"
    assert forecast.hypothesis == "cex_multi_horizon_market_oracle"
    assert forecast.execution_eligible is False
    assert forecast.expected_net_bps is not None and forecast.expected_net_bps > 0
    receipt = forecast.inputs["cex_market_oracle"]
    assert receipt["authority"] == "research_forecast_only"
    assert receipt["execution_eligible"] is False
    assert receipt["orders_submitted"] == 0
    assert receipt["available_horizons"] == ["1h", "24h", "5h"]


def test_worker_signal_federation_emits_research_only_breakout_receipt():
    cfg = Phase2Config(
        phase2_worker_signal_models=("worker_signal_breakout_v1",),
        phase2_worker_signal_min_strength=0.30,
    )
    federation = WorkerSignalFederation(cfg, ResearchCostModel())
    model = federation.models[0]
    forecast = model.forecast(
        feature(
            values={
                "feature_version": "phase2.v1",
                "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.78},
                "worker_series": worker_series(),
            },
            atr_pct=0.012,
            return_5=0.012,
            return_zscore=2.0,
        ),
        horizon_seconds=300,
    )

    assert forecast.abstain is False
    assert forecast.direction == "UP"
    assert forecast.model_id == "worker_signal_breakout_v1"
    assert forecast.execution_eligible is False
    assert forecast.inputs["worker_signal_receipt"]["execution_authority"] == "none"
    assert forecast.inputs["worker_signal_receipt"]["orders_submitted"] == 0
    assert forecast.inputs["worker_signal_receipt"]["series_points"] >= 50


def test_worker_signal_federation_abstains_without_real_phase1_series():
    cfg = Phase2Config(phase2_worker_signal_models=("worker_signal_breakout_v1",))
    federation = WorkerSignalFederation(cfg, ResearchCostModel())
    forecast = federation.models[0].forecast(feature(), horizon_seconds=300)

    assert forecast.abstain is True
    assert "worker_series_unavailable" in forecast.reasons
    assert forecast.inputs["worker_signal_receipt"]["execution_authority"] == "none"


def test_worker_signal_rsi_uses_base_worker_proposal_without_crashing():
    cfg = Phase2Config(phase2_worker_signal_models=("worker_signal_rsi_v1",))
    federation = WorkerSignalFederation(cfg, ResearchCostModel())
    forecast = federation.models[0].forecast(
        feature(
            values={
                "feature_version": "phase2.v1",
                "regime_inputs": {"regime_hint": "quiet_range", "confidence": 0.78},
                "worker_series": worker_series([100.0 - index * 0.08 for index in range(75)]),
            },
            atr_pct=0.01,
            return_5=-0.010,
            return_zscore=-2.0,
        ),
        horizon_seconds=300,
    )

    assert forecast.reason != "worker_proposal_failed"
    assert forecast.inputs["worker_signal_receipt"]["worker_id"] == "WORKER-RSI"


def test_worker_signal_counterfactuals_settle_raw_signal_without_execution_authority():
    cfg = Phase2Config(
        phase2_worker_signal_models=("worker_signal_rsi2_v1",),
        phase2_worker_signal_minimum_edge_multiple=999.0,
    )
    federation = WorkerSignalFederation(cfg, ResearchCostModel())
    forecast = federation.models[0].forecast(
        feature(
            values={
                "feature_version": "phase2.v1",
                "regime_inputs": {"regime_hint": "quiet_range", "confidence": 0.78},
                "worker_series": worker_series([100.0 - index * 0.08 for index in range(75)]),
            },
            atr_pct=0.002,
            return_5=-0.006,
            return_zscore=-1.2,
        ),
        horizon_seconds=300,
    )

    assert forecast.abstain is False
    assert forecast.reason == "worker_signal_counterfactual_cost_refused"
    assert forecast.execution_eligible is False
    assert forecast.inputs["worker_counterfactual"]["execution_authority"] == "none"
    assert forecast.inputs["worker_counterfactual"]["cost_gate_passed"] is False


def test_cex_multi_horizon_oracle_abstains_when_horizons_disagree():
    model = CexMultiHorizonMarketOracle(ResearchCostModel(), minimum_edge_multiple=1.1)
    forecast = model.forecast(
        feature(values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "balanced_transition", "confidence": 0.62},
            "cex_market_oracle": oracle_context(change_1h=95.0, change_5h=-110.0, change_24h=75.0),
        }),
        horizon_seconds=900,
    )

    assert forecast.abstain is True
    assert "oracle_horizon_agreement_low" in forecast.reasons
    assert forecast.execution_eligible is False


def test_data_store_builds_cex_oracle_context_from_observation_snapshots(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "oracle_context.db"))
    now = time.time()
    rows = [
        (now - 31 * 3600, 96.0),
        (now - 25 * 3600, 97.0),
        (now - 6 * 3600, 99.0),
        (now - 2 * 3600, 100.0),
        (now - 10, 102.0),
    ]
    with store._lock:
        cur = store.conn.cursor()
        for index, (ts, price) in enumerate(rows):
            cur.execute(
                """
                INSERT INTO observation_snapshots
                (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
                 depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
                 data_quality, observation_eligible, execution_eligible, rejection_reasons, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"run-{index}",
                    ts,
                    "kraken",
                    "TEST/USD",
                    price,
                    100_000_000.0,
                    3.0 + index * 0.1,
                    1_000_000.0,
                    1.2,
                    0.5,
                    0.1,
                    1.0,
                    1,
                    0,
                    "[]",
                    "{}",
                ),
            )
        store.conn.commit()

    context = store.cex_market_oracle_context("TEST/USD", venue="kraken", as_of_ts=now)

    assert context["schema"] == "cex_market_oracle_context_v1"
    assert context["available_horizons"] >= 2
    assert context["horizons"]["1h"]["change_bps"] > 0
    assert context["horizons"]["5h"]["change_bps"] > 0
    assert context["latest"]["price"] == 102.0
    assert context["execution_eligible"] is False


def test_commons_verifier_resolves_exact_ticket_beyond_recent_window(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "commons_exact.db"))
    governor = CommonsPhase2Governor(Phase2Config(), store)
    now = time.time()
    target = governor.issue_ticket(
        observation_run_id="obs-target",
        venue="kraken",
        candidate={"values": {}},
        feature=feature(),
        horizon_seconds=300,
        created_ts=now,
    )
    assert store.persist_commons_pool_work_ticket(target)
    for index in range(30):
        newer = dict(target)
        newer["ticket_id"] = f"newer-{index}"
        newer["created_ts"] = now + index + 1
        assert store.persist_commons_pool_work_ticket(newer)

    inference = {
        "task_class": "phase2_challenger_forecast",
        "phase_scope": 2,
        "created_ts": now,
        "ticket_id": target["ticket_id"],
        "challenge_nonce": target["challenge_nonce"],
        "input_root": target["input_root"],
    }
    inference["signature"] = governor._signature_for(inference)
    packet = {
        "adoption_receipt": {
            "authority_ceiling": "proposal_only",
            "local_reproduction_verdict": "PASS",
            "adoption_decision": "ACCEPTED_CHALLENGER_FORECAST",
        },
        "inference_receipt": inference,
    }

    allowed, reasons = governor.verify_adopted_packet(packet, now_ts=now + 1)

    assert allowed is True
    assert reasons == []

    quarantined_cfg = Phase2Config()
    quarantined_cfg.phase2_federation_quarantined_models = {
        "candidate_freqai_transparent_linear_v1": "negative_outcome_blind_expansion"
    }
    quarantined_governor = CommonsPhase2Governor(quarantined_cfg, store)
    wrapped = dict(inference)
    wrapped["result_summary"] = {
        "model_id": "beast_crystal_selected::candidate_freqai_transparent_linear_v1"
    }
    wrapped["signature"] = quarantined_governor._signature_for(wrapped)
    blocked_packet = {**packet, "inference_receipt": wrapped}

    allowed, reasons = quarantined_governor.verify_adopted_packet(blocked_packet, now_ts=now + 1)

    assert allowed is False
    assert reasons == ["source_model_quarantined:candidate_freqai_transparent_linear_v1"]


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
    assert "candidate_triune_polyphonic_synthesis_v1" in model_ids
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
    expected_model_count = len(swarm.competition.all_model_ids)
    assert len(payload["forecasts"]) == expected_model_count * len(swarm.horizons)
    assert all(row["execution_eligible"] is False for row in payload["forecasts"])
    assert all(row["order_intent"] is None for row in payload["forecasts"])
    assert any(row["model_id"] == "worker_signal_breakout_v1" for row in payload["forecasts"])
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
    assert settlement["settled"] == expected_model_count
    assert settlement["orders_submitted"] == 0
    outcomes = store.get_hypothesis_outcomes(limit=50)
    assert len(outcomes) == expected_model_count
    scorecard = store.get_hypothesis_scorecard()
    assert len(scorecard["models"]) == expected_model_count
    assert scorecard["execution_eligible"] is False
    assert "demotion_recommendations" in scorecard
    assert "expectancy_breakdown" in scorecard

    readiness = store.get_phase2_readiness(min_forecasts=1, min_settled_non_abstain=1, min_distinct_days=1)
    assert readiness["execution_eligible"] is False
    assert readiness["orders_submitted"] == 0


def test_settlement_can_target_recent_worker_backlog_without_stale_starvation(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "phase2_targeted_settlement.db"))
    now = time.time()
    old_target = now - 86_400
    recent_target = now - 60
    rows = [
        (
            "old-stale-worker",
            "run-old",
            "obs-old",
            old_target - 300,
            old_target,
            "kraken",
            "ETH/USD",
            "worker_signal_breakout_v1",
            "worker_signal_breakout",
            300,
            "UP",
            100.0,
            0.6,
            8.0,
            1.0,
            7.0,
            0.7,
            0,
            "test_old",
            0,
            0,
            "{}",
        ),
        (
            "recent-worker",
            "run-new",
            "obs-new",
            recent_target - 300,
            recent_target,
            "kraken",
            "ETH/USD",
            "worker_signal_breakout_v1",
            "worker_signal_breakout",
            300,
            "UP",
            100.0,
            0.6,
            8.0,
            1.0,
            7.0,
            0.7,
            0,
            "test_recent",
            0,
            0,
            "{}",
        ),
    ]
    store.conn.executemany(
        """
        INSERT INTO hypothesis_forecasts
        (forecast_id, run_id, observation_run_id, ts, target_ts, venue, symbol,
         model_id, hypothesis, horizon_seconds, direction, entry_price,
         probability_positive_net, expected_move_bps, expected_cost_bps,
         expected_net_bps, raw_score, abstain, reason, settled,
         execution_eligible, payload)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    store.conn.execute(
        """
        INSERT INTO observation_snapshots
        (run_id, ts, venue, symbol, price, data_quality, observation_eligible, payload)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        ("obs-exit", recent_target + 1, "kraken", "ETH/USD", 101.0, 1.0, 1, "{}"),
    )
    store.conn.commit()

    settlement = store.settle_mature_hypothesis_forecasts(
        now_ts=now,
        tolerance_sec=120,
        limit=1,
        min_target_ts=now - 3600,
        model_prefix="worker_signal_",
    )

    assert settlement["examined"] == 1
    assert settlement["settled"] == 1
    assert store.conn.execute(
        "SELECT settled FROM hypothesis_forecasts WHERE forecast_id='recent-worker'"
    ).fetchone()[0] == 1
    assert store.conn.execute(
        "SELECT settled FROM hypothesis_forecasts WHERE forecast_id='old-stale-worker'"
    ).fetchone()[0] == 0


def test_worker_signal_negative_memory_blocks_repeated_bad_slice():
    class AlwaysBuyWorker:
        name = "WORKER-ALWAYS-BUY"

        def propose(self, closes, volumes=None, latest_price=0.0):
            return {"action": "BUY", "signal_strength": 0.9, "notes": "test buy"}

    model = WorkerSignalModel(
        cost_model=ResearchCostModel(),
        worker=AlwaysBuyWorker(),
        model_id="worker_signal_test_v1",
        hypothesis="worker_signal_test",
        family="test",
        min_data_quality=0.99,
        minimum_edge_multiple=1.1,
        min_strength=0.1,
        settle_counterfactuals=True,
        negative_memory_enabled=True,
        negative_memory_min_samples=3,
        negative_memory_max_mean_net_bps=-5.0,
        negative_memory_min_directional_hit_rate=0.42,
    )
    closes = [100.0 + (idx * 0.01) for idx in range(60)]
    f = feature(values={
        "feature_version": "phase2.v1",
        "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.72},
        "worker_series": {"schema": "test", "timeframe": "1m", "closes": closes, "volumes": [1000.0] * len(closes)},
        "phase2_worker_signal_memory": {
            "exact": {
                "worker_signal_test_v1|300|UP": {
                    "samples": 5,
                    "mean_net_bps": -12.0,
                    "directional_hit_rate": 0.2,
                }
            },
            "model": {},
        },
    })

    forecast = model.forecast(f, horizon_seconds=300)

    assert forecast.abstain is True
    assert forecast.reason == "worker_signal_negative_memory"


def test_worker_signal_forecast_carries_triune_worker_mind_receipt():
    cfg = Phase2Config(
        phase2_worker_signal_models=("worker_signal_breakout_v1",),
        phase2_worker_signal_min_strength=0.30,
    )
    federation = WorkerSignalFederation(cfg, ResearchCostModel())
    closes = [100.0] * 55 + [103.0]
    f = feature(values={
        "feature_version": "phase2.v1",
        "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.82},
        "worker_series": {"schema": "test", "timeframe": "1m", "closes": closes, "volumes": [1000.0] * len(closes)},
    })

    forecast = federation.models[0].forecast(f, horizon_seconds=300)

    triune = forecast.inputs["triune_worker_mind"]
    assert triune["schema"] == "hivenance_triune_worker_mind_v1"
    assert triune["metatron"]["role"] == "METATRON_SYNTHESIS"
    assert triune["michael"]["role"] == "MICHAEL_VALIDATOR"
    assert triune["loki"]["role"] == "LOKI_ADVERSARY"
    assert triune["execution_authority"] == "none"


def test_worker_signal_loki_vetoes_stable_pair_cost_trap():
    class AlwaysBuyWorker:
        name = "WORKER-ALWAYS-BUY"

        def propose(self, closes, volumes=None, latest_price=0.0):
            return {"action": "BUY", "signal_strength": 0.95, "notes": "test stable buy"}

    model = WorkerSignalModel(
        cost_model=ResearchCostModel(),
        worker=AlwaysBuyWorker(),
        model_id="worker_signal_test_v1",
        hypothesis="worker_signal_test",
        family="trend",
        min_data_quality=0.99,
        minimum_edge_multiple=1.1,
        min_strength=0.1,
        settle_counterfactuals=True,
        triune_mind_enabled=True,
        triune_loki_enabled=True,
        triune_loki_veto_risk=0.82,
    )
    closes = [1.0 + (idx * 0.000001) for idx in range(60)]
    f = feature(
        symbol="USDC/USDT",
        price=1.0,
        spread_bps=4.0,
        return_5=0.00001,
        return_zscore=0.02,
        atr_pct=0.00002,
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "quiet_range", "confidence": 0.80},
            "worker_series": {"schema": "test", "timeframe": "1m", "closes": closes, "volumes": [1000.0] * len(closes)},
        },
    )

    forecast = model.forecast(f, horizon_seconds=300)

    assert forecast.abstain is True
    assert forecast.reason == "worker_signal_loki_veto"
    loki = forecast.inputs["triune_worker_mind"]["loki"]
    assert loki["status"] == "vetoed"
    assert any(item["challenge"] == "stable_pair_spread_trap" for item in loki["challenges"])


def test_worker_coalition_meta_model_emits_research_only_forecast_when_voters_align():
    cfg = Phase2Config(
        phase2_worker_coalition_min_strength=0.30,
        phase2_worker_coalition_min_voters=2,
        phase2_worker_coalition_min_agreement=0.50,
    )
    model = WorkerCoalitionMetaModel(cfg, ResearchCostModel())
    closes = [100.0 + (idx * 0.03) for idx in range(55)] + [104.0, 105.0]
    f = feature(
        return_5=0.018,
        return_zscore=2.4,
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.84},
            "worker_series": {"schema": "test", "timeframe": "1m", "closes": closes, "volumes": [1500.0] * len(closes)},
        },
    )

    forecast = model.forecast(f, horizon_seconds=300)

    assert forecast.abstain is False
    assert forecast.reason == "worker_coalition_passed"
    assert forecast.execution_eligible is False
    assert forecast.inputs["worker_coalition_receipt"]["schema"] == "hivenance_worker_coalition_receipt_v1"
    assert forecast.inputs["worker_coalition_receipt"]["execution_authority"] == "none"
    meta = forecast.inputs["worker_coalition_receipt"]["meta_strategy_council"]
    assert meta["schema"] == "hivenance_meta_strategy_council_v1"
    assert "mean_reversion" in meta["blocked_families"]
    assert set(meta["allowed_families"]) == {"breakout", "momentum", "trend"}
    assert any(
        voter["status"] == "muted_by_meta_strategy_council"
        and voter["family"] == "mean_reversion"
        for voter in forecast.inputs["worker_coalition_receipt"]["voters"]
    )
    coalition = forecast.inputs["worker_coalition_receipt"]["coalition"]
    assert coalition["allowed_voters"] >= 2
    assert coalition["agreement"] >= 0.50
    assert forecast.inputs["worker_coalition_receipt"]["orders_submitted"] == 0


def test_worker_coalition_symbol_class_budget_controls_family_votes():
    cfg = Phase2Config(
        phase2_worker_coalition_min_strength=0.30,
        phase2_worker_coalition_min_voters=1,
        phase2_worker_coalition_min_agreement=0.40,
    )
    model = WorkerCoalitionMetaModel(cfg, ResearchCostModel())
    closes = [100.0 + (idx * 0.03) for idx in range(55)] + [104.0, 105.0]
    f = feature(
        return_5=0.018,
        return_zscore=2.4,
        values={
            "feature_version": "phase2.v1",
            "symbol_class": "high_spread_context",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.84},
            "worker_series": {"schema": "test", "timeframe": "1m", "closes": closes, "volumes": [1500.0] * len(closes)},
        },
    )

    forecast = model.forecast(f, horizon_seconds=300)
    receipt = forecast.inputs["worker_coalition_receipt"]
    budget = receipt["symbol_class_budget"]

    assert budget["schema"] == "hivenance_worker_coalition_symbol_class_budget_v1"
    assert budget["budget_name"] == "high_spread"
    assert set(budget["families"]) == {"mean_reversion", "trend"}
    assert receipt["coalition"]["symbol_class_budget"]["minimum_edge_multiple"] == 1.9
    assert any(
        voter["family"] == "breakout"
        and voter["status"] == "muted_by_meta_strategy_council"
        and voter["reason"] == "family_not_allowed_in_current_meta_or_symbol_class_lane"
        for voter in receipt["voters"]
    )


def test_worker_coalition_partial_vote_settles_as_refused_counterfactual():
    cfg = Phase2Config(
        phase2_worker_coalition_models=("worker_signal_momentum_v1",),
        phase2_worker_coalition_min_strength=0.30,
        phase2_worker_coalition_min_voters=2,
        phase2_worker_coalition_settle_counterfactuals_enabled=True,
    )
    model = WorkerCoalitionMetaModel(cfg, ResearchCostModel())
    closes = [100.0 + (idx * 0.01) for idx in range(55)] + [102.0]
    f = feature(
        return_5=0.014,
        return_zscore=1.8,
        values={
            "feature_version": "phase2.v1",
            "regime_inputs": {"regime_hint": "trend_expansion", "confidence": 0.76},
            "worker_series": {"schema": "test", "timeframe": "1m", "closes": closes, "volumes": [1200.0] * len(closes)},
        },
    )

    forecast = model.forecast(f, horizon_seconds=300)

    assert forecast.abstain is False
    assert forecast.reason == "worker_coalition_insufficient_voters_counterfactual"
    assert forecast.execution_eligible is False
    assert forecast.inputs["worker_coalition_counterfactual"]["authority"] == "research_settlement_only"
    assert forecast.inputs["worker_coalition_counterfactual"]["execution_authority"] == "none"


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
