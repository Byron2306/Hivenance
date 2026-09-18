from __future__ import annotations

import json

from strategies.relative_value_lab.contracts import ForwardRelativeForecast, RelativeMarketState
from strategies.relative_value_lab.pair_lab import PairDiagnostics
from strategies.relative_value_lab.research_council import LocalOllamaResearchCouncil


def diagnostics() -> PairDiagnostics:
    return PairDiagnostics(
        pair_id="A/USD__B/USD",
        samples=240,
        correlation_returns=0.6,
        hedge_alpha=0.1,
        hedge_ratio=1.0,
        hedge_r2=0.7,
        spread_mean=0.0,
        spread_std=0.01,
        spread_last=-0.02,
        spread_zscore=-2.0,
        ar1_intercept=0.0,
        ar1_phi=0.9,
        ar1_r2=0.7,
        ou_mean_reversion_speed_per_sec=0.02,
        ou_equilibrium=0.0,
        half_life_seconds=34.6,
        structural_break_score=0.2,
        structural_break_state="STABLE",
        stability_score=0.8,
        eligible=True,
        rejection_reasons=(),
    )


def state() -> RelativeMarketState:
    return RelativeMarketState(
        schema="hivenance_relative_market_state_v1",
        pair_id="A/USD__B/USD",
        timestamp_ms=1,
        spread=-0.02,
        spread_zscore=-2.0,
    )


def forecast() -> ForwardRelativeForecast:
    return ForwardRelativeForecast(
        schema="hivenance_forward_relative_forecast_v1",
        forecast_id="rvf_test",
        pair_id="A/USD__B/USD",
        timestamp_ms=1,
        horizon_seconds=60,
        model_id="relative_value_ou_mean_reversion_v1",
        expected_relative_move_bps=12.0,
        prediction_lower_bps=2.0,
        prediction_upper_bps=22.0,
        probability_positive_gross=0.75,
        expected_cost_bps=4.0,
        expected_net_bps=8.0,
        uncertainty=5.0,
        calibration_state="TEST",
        abstain=False,
        reason="test",
        direction="LONG_A_SHORT_B",
    )


class StubCouncil(LocalOllamaResearchCouncil):
    def _call_ollama(self, packet):
        assert packet["forbidden_authority"]["execution"] is True
        return json.dumps({
            "contradictions": ["flow evidence is missing"],
            "missing_evidence": ["longer structural history"],
            "alternative_hypotheses": ["common-driver move"],
            "analogous_slices": ["prior range regime"],
            "suggested_falsification_tests": ["replay matched random entries"],
            "explanation_confidence": 0.61,
        })


class FailingCouncil(LocalOllamaResearchCouncil):
    def _call_ollama(self, packet):
        raise RuntimeError("offline")


def test_local_research_council_returns_advisory_receipt_only():
    receipt = StubCouncil(model="stub").review(
        state=state(),
        diagnostics=diagnostics(),
        forecast=forecast(),
    )
    assert receipt.contradictions == ("flow evidence is missing",)
    assert receipt.missing_evidence == ("longer structural history",)
    assert receipt.explanation_confidence == 0.61
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
    assert receipt.authority.endswith("no_execution_or_promotion_authority")


def test_local_research_council_failure_does_not_break_deterministic_pipeline():
    receipt = FailingCouncil(model="stub").review(
        state=state(),
        diagnostics=diagnostics(),
        forecast=forecast(),
    )
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
    assert receipt.explanation_confidence is None
    assert receipt.missing_evidence == ("local_adviser_unavailable:RuntimeError",)
