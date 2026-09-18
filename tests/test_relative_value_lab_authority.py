from __future__ import annotations

from pathlib import Path

from agents.phoenix_authority import PhoenixAuthorityGuard, PROTECTED_ACTIONS
from strategies.relative_value_lab.contracts import (
    ForwardRelativeForecast,
    PairRelationshipCrystal,
    ResearchCouncilReceipt,
    RelativeMarketState,
    RELATIVE_VALUE_AUTHORITY,
)


COMPONENTS = (
    "relative_value_microstructure",
    "relative_value_pair_lab",
    "relative_value_forecaster",
    "relative_value_research_council",
    "relative_value_harmonic_governance",
    "relative_value_harmony_law",
    "relative_value_waggle_protocol",
    "relative_value_musical_cognition",
    "relative_value_polyphonic_entrainment",
    "relative_value_governance_epoch",
    "relative_value_conducting_queen",
    "relative_value_market_hunting",
    "relative_value_colony_correlation",
    "relative_value_ml_challenger",
    "relative_value_edge_chorus",
    "relative_value_notation_token",
    "relative_value_graph",
    "relative_value_execution_lab",
)


def test_relative_value_components_are_research_bounded():
    guard = PhoenixAuthorityGuard()
    for component in COMPONENTS:
        contract = guard.component_contract(component)
        assert contract["live_allowed"] is False
        assert contract["execution_authority"] == "none"
        assert contract["promotion_authority"] == "none"
        assert contract["resume_authority"] == "none"
        assert contract["scaling_authority"] == "none"


def test_relative_value_components_cannot_gain_any_protected_authority():
    guard = PhoenixAuthorityGuard()
    for component in COMPONENTS:
        for action in PROTECTED_ACTIONS:
            decision = guard.decision(component, action)
            assert decision.allowed is False, (component, action, decision.to_dict())


def test_relative_value_components_can_do_bounded_research():
    guard = PhoenixAuthorityGuard()
    for component in COMPONENTS:
        assert guard.decision(component, "observe").allowed is True
        assert guard.decision(component, "generate_proposal").allowed is True


def test_pair_relationship_crystal_defaults_to_no_execution():
    crystal = PairRelationshipCrystal(
        schema="hivenance_pair_relationship_crystal_v1",
        pair_id="DOGE_SOL",
        base_symbol="DOGE/USD",
        quote_symbol="SOL/USD",
        venue="kraken",
        observed_at_ms=1,
        lookback_seconds=3600,
        direct_route_available=False,
        relationship_method="research_test",
    )
    assert crystal.authority == RELATIVE_VALUE_AUTHORITY
    assert crystal.execution_eligible is False


def test_relative_market_state_defaults_to_no_execution():
    state = RelativeMarketState(
        schema="hivenance_relative_market_state_v1",
        pair_id="DOGE_SOL",
        timestamp_ms=1,
        spread=0.0,
        spread_zscore=0.0,
    )
    assert state.execution_eligible is False


def test_forward_forecast_is_research_only_even_when_positive():
    forecast = ForwardRelativeForecast(
        schema="hivenance_forward_relative_forecast_v1",
        forecast_id="f1",
        pair_id="DOGE_SOL",
        timestamp_ms=1,
        horizon_seconds=60,
        model_id="test",
        expected_relative_move_bps=20.0,
        prediction_lower_bps=10.0,
        prediction_upper_bps=30.0,
        probability_positive_gross=0.9,
        expected_cost_bps=4.0,
        expected_net_bps=16.0,
        uncertainty=0.1,
        calibration_state="TEST",
        abstain=False,
        reason="unit_test",
    )
    assert forecast.expected_net_bps > 0
    assert forecast.execution_eligible is False
    assert forecast.authority == RELATIVE_VALUE_AUTHORITY


def test_research_council_can_never_promote():
    receipt = ResearchCouncilReceipt(
        schema="hivenance_relative_value_research_council_v1",
        receipt_id="r1",
        created_at_ms=1,
        subject_id="f1",
        adviser_model="ollama/test",
    )
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_relative_value_package_contains_no_private_or_order_api_calls():
    root = Path(__file__).resolve().parents[1] / "strategies" / "relative_value_lab"
    forbidden = (
        ".create_order(",
        ".fetch_balance(",
        "submit_order(",
        "transmit_order(",
        "private_key",
        "apiSecret",
        "apiKey",
    )
    for path in root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{token} found in {path}"