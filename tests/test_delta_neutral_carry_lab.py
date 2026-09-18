from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from strategies.volatility_breakout.delta_neutral_carry_lab import (
    default_cost_assumptions,
    evaluate_carry_opportunity,
    run_delta_neutral_carry_lab,
)


def _cfg(**overrides) -> SimpleNamespace:
    base = dict(
        exchange="kraken",
        phase3_venue_economics_receipt="",
        phase3_maker_fee_bps=10.0,
        phase3_taker_fee_bps=20.0,
        derivatives_trend_maker_fee_bps=2.0,
        derivatives_trend_taker_fee_bps=5.0,
        delta_neutral_carry_spread_slippage_bps=6.0,
        delta_neutral_carry_collateral_cost_bps=2.0,
        delta_neutral_carry_funding_uncertainty_bps=3.0,
        delta_neutral_carry_rebalance_reserve_bps=2.0,
        delta_neutral_carry_safety_buffer_bps=3.0,
        delta_neutral_carry_min_required_net_return_bps=15.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_evaluate_carry_opportunity_matches_exact_formula() -> None:
    payload = evaluate_carry_opportunity(
        symbol="BTC/USD",
        funding_income_bps=100.0,
        spot_fees_bps=10.0,
        futures_fees_bps=5.0,
        spread_slippage_bps=6.0,
        collateral_cost_bps=2.0,
        funding_uncertainty_bps=3.0,
        rebalance_reserve_bps=2.0,
        safety_buffer_bps=3.0,
        required_net_return_bps=15.0,
    )

    # net_edge_bps = income - (all eight cost terms), exactly as specified.
    expected_total_cost = 10.0 + 5.0 + 6.0 + 2.0 + 3.0 + 2.0 + 3.0
    assert payload["total_cost_bps"] == expected_total_cost
    assert payload["net_edge_bps"] == 100.0 - expected_total_cost
    assert payload["accepted"] is True
    assert payload["leverage"] == 1
    assert payload["execution_authority"] == "none"
    assert payload["structure"] == "long_spot_short_perpetual"


def test_evaluate_carry_opportunity_rejects_below_required_return() -> None:
    payload = evaluate_carry_opportunity(
        symbol="BTC/USD",
        funding_income_bps=20.0,
        spot_fees_bps=10.0,
        futures_fees_bps=5.0,
        spread_slippage_bps=6.0,
        collateral_cost_bps=2.0,
        funding_uncertainty_bps=3.0,
        rebalance_reserve_bps=2.0,
        safety_buffer_bps=3.0,
        required_net_return_bps=15.0,
    )

    assert payload["accepted"] is False
    assert "net_edge_below_required_return" in payload["reasons"]


def test_evaluate_carry_opportunity_flags_manual_funding_income_source() -> None:
    payload = evaluate_carry_opportunity(
        symbol="ETH/USD",
        funding_income_bps=200.0,
        spot_fees_bps=1.0,
        futures_fees_bps=1.0,
        spread_slippage_bps=1.0,
        collateral_cost_bps=1.0,
        funding_uncertainty_bps=1.0,
        rebalance_reserve_bps=1.0,
        safety_buffer_bps=1.0,
        required_net_return_bps=15.0,
    )

    # Never silently claims live/verified funding data.
    assert payload["funding_income_source"] == "manual_input_no_live_feed"
    assert "funding_income_is_a_manual_research_input_not_a_live_feed" in payload["reasons"]


def test_default_cost_assumptions_never_reuses_spot_receipt_for_futures_leg() -> None:
    cfg = _cfg()
    costs = default_cost_assumptions(cfg)
    assert costs["futures_fees_bps"] == 2.0 + 5.0  # kraken_futures research defaults
    assert costs["spot_fees_bps"] == 10.0 + 20.0  # kraken unverified spot defaults


def test_run_delta_neutral_carry_lab_persists_receipt() -> None:
    conn = sqlite3.connect(":memory:")
    cfg = _cfg()

    payload = run_delta_neutral_carry_lab(
        conn,
        cfg,
        symbol="BTC/USD",
        funding_income_bps=120.0,
    )

    row = conn.execute(
        "SELECT accepted, payload FROM delta_neutral_carry_receipts WHERE receipt_id=?",
        (payload["receipt_id"],),
    ).fetchone()
    assert row is not None
    stored = json.loads(row[1])
    assert stored["receipt_id"] == payload["receipt_id"]
    assert bool(row[0]) == payload["accepted"]


def test_run_delta_neutral_carry_lab_cost_override() -> None:
    conn = sqlite3.connect(":memory:")
    cfg = _cfg()

    payload = run_delta_neutral_carry_lab(
        conn,
        cfg,
        symbol="BTC/USD",
        funding_income_bps=120.0,
        spot_fees_bps=0.0,
    )

    assert payload["cost_terms_bps"]["spot_fees_bps"] == 0.0
