from pathlib import Path

from strategies.relative_value_lab.phase13_book_ledger import Phase13BookLedger
from strategies.relative_value_lab.phase13_book_router import Phase13ForecastBookRow


def row(book="FULL_HIVE_FROZEN",model="m1"):
    return Phase13ForecastBookRow(
        freeze_id="p13f_test",book_id=book,world_state_id="w1",
        world_state_hash="sha256:"+"a"*64,symbol="BTC/USD",
        timestamp_ms=1000,horizon_seconds=300,model_id=model,direction="UP",
        abstain=False,probability_positive_net=.6,expected_move_bps=10.0,
        expected_cost_bps=2.0,expected_net_bps=8.0,envelope_id=None,
    )


def test_phase13_ledger_keeps_books_isolated(tmp_path:Path):
    ledger=Phase13BookLedger(tmp_path/"p13.db")
    try:
        assert ledger.persist_forecasts([row(),row("ADAPTIVE_HIVE")])==2
        pending=ledger.pending_forecasts(freeze_id="p13f_test")
        assert {x["book_id"] for x in pending}=={"FULL_HIVE_FROZEN","ADAPTIVE_HIVE"}
        first=pending[0]
        ledger.persist_settlement(
            forecast_row_id=first["row_id"],freeze_id=first["freeze_id"],
            book_id=first["book_id"],world_state_id=first["world_state_id"],
            world_state_hash=first["world_state_hash"],symbol=first["symbol"],
            timestamp_ms=first["timestamp_ms"],horizon_seconds=first["horizon_seconds"],
            model_id=first["model_id"],settled_ts=400.0,realized_net_bps=5.0,
            realized_cost_bps=2.0,fill_status="SETTLED",filled=True,payload={},
        )
        remaining=ledger.pending_forecasts(freeze_id="p13f_test")
        assert len(remaining)==1
        assert remaining[0]["book_id"]!=first["book_id"]
    finally:
        ledger.close()
