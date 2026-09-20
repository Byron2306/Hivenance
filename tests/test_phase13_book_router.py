from strategies.relative_value_lab.phase13_book_router import route_phase13_forecast_books
from strategies.volatility_breakout.models import Forecast


def fc(model_id,direction="UP",abstain=False):
    return Forecast(
        symbol="BTC/USD",timestamp_ms=1000,horizon_seconds=300,
        model_id=model_id,hypothesis=model_id,direction="ABSTAIN" if abstain else direction,
        probability_positive_net=None if abstain else .55,
        expected_move_bps=None if abstain else 10.0,
        expected_cost_bps=2.0,expected_net_bps=None if abstain else 8.0,
        raw_score=.5,uncertainty=.5,calibration_state="T",
        feature_version="v",abstain=abstain,reason="t",reasons=(),inputs={},
        execution_eligible=False,
    )


def test_phase13_router_populates_confirmatory_and_control_books_same_world():
    frozen=[
        fc("breakout_continuation_v1"),
        fc("candidate_cex_multi_horizon_oracle_v1"),
        fc("baseline_simple_momentum_v1"),
        fc("baseline_simple_mean_reversion_v1"),
        fc("baseline_deterministic_random_v1"),
        fc("baseline_no_trade_v1",abstain=True),
    ]
    adaptive=list(frozen)
    rows=route_phase13_forecast_books(
        freeze_id="p13f_test",
        world_state_id="w1",
        world_state_hash="sha256:"+"a"*64,
        frozen_full_forecasts=frozen,
        adaptive_forecasts=adaptive,
        phoenix_primary_ids=["breakout_continuation_v1","exhaustion_mean_reversion_v1"],
    )
    books={row.book_id for row in rows}
    assert {
        "FULL_HIVE_FROZEN","ADAPTIVE_HIVE","PHOENIX_ONLY","CEX_ORACLE_ONLY",
        "SIMPLE_MOMENTUM","SIMPLE_REVERSION","DETERMINISTIC_RANDOM","NO_TRADE",
    } <= books
    assert {row.world_state_id for row in rows}=={"w1"}
    assert {row.freeze_id for row in rows}=={"p13f_test"}
