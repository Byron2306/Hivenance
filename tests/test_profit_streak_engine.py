from strategies.volatility_breakout.profit_streak_engine import EquityPoint, ProfitStreakEngine


def test_micro_retracements_are_evidence_not_automatic_failure():
    engine = ProfitStreakEngine(fast_horizon_sec=5, slow_horizon_sec=10, max_retracement_usd=0.10)
    equities = [
        1000.00, 1000.01, 1000.02, 1000.03, 1000.04,
        1000.05, 1000.06, 1000.07, 1000.08, 1000.09,
        1000.12, 1000.11, 1000.14, 1000.13, 1000.17,
        1000.18, 1000.16, 1000.21, 1000.23, 1000.24,
        1000.20, 1000.17, 1000.12, 1000.08, 1000.03,
    ]
    kinds = []
    for ts, equity in enumerate(equities):
        kinds.extend(event["kind"] for event in engine.observe(EquityPoint(ts, equity, cumulative_cost_usd=0.01)))
    engine.finalize()
    assert "STREAK_START" in kinds
    assert "STREAK_RETRACE" in kinds
    receipts = engine.completed_receipts()
    assert receipts
    assert receipts[0]["peak_equity_usd"] >= 1000.23
    assert receipts[0]["retracements"] >= 1
    assert receipts[0]["max_retracement_usd"] > 0


def test_engine_has_no_execution_authority():
    engine = ProfitStreakEngine()
    snapshot = engine.snapshot()
    assert snapshot["authority"] == "paper_observation_only_no_order_authority"


def test_cost_and_velocity_are_bound_into_receipt():
    engine = ProfitStreakEngine(fast_horizon_sec=2, slow_horizon_sec=4, max_retracement_usd=0.10)
    observations = [
        (0, 1000.00, 0.00), (1, 1000.01, 0.00), (2, 1000.03, 0.01),
        (3, 1000.05, 0.01), (4, 1000.08, 0.02), (5, 1000.10, 0.02),
        (6, 1000.12, 0.03), (7, 1000.14, 0.03),
    ]
    for ts, equity, cost in observations:
        engine.observe(EquityPoint(ts, equity, cumulative_cost_usd=cost))
    engine.finalize()
    receipt = engine.completed_receipts()[0]
    assert receipt["cost_usd"] >= 0
    assert "profit_velocity_usd_per_sec" in receipt
    assert "cost_to_gross_ratio" in receipt
