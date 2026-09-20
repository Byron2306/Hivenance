import sqlite3
from pathlib import Path

from strategies.relative_value_lab.phase13_book_ledger import Phase13BookLedger
from strategies.relative_value_lab.phase13_book_router import Phase13ForecastBookRow
from strategies.relative_value_lab.phase13_settlement_runtime import settle_mature_phase13_books


def test_phase13_settlement_uses_later_public_tape(tmp_path:Path):
    market=tmp_path/"market.db"
    con=sqlite3.connect(market)
    con.execute("""
    CREATE TABLE observation_snapshots(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT, ts REAL, venue TEXT, symbol TEXT, price REAL,
      quote_volume_24h REAL, spread_bps REAL, depth_usd_25bps REAL,
      volatility_expansion REAL, volume_zscore REAL, book_imbalance REAL,
      data_quality REAL, observation_eligible INTEGER,
      execution_eligible INTEGER DEFAULT 0, rejection_reasons TEXT, payload TEXT
    )
    """)
    con.execute(
        "INSERT INTO observation_snapshots(run_id,ts,venue,symbol,price,spread_bps,depth_usd_25bps,data_quality,observation_eligible) VALUES(?,?,?,?,?,?,?,?,?)",
        ("r1",1000.5,"kraken","BTC/USD",100.0,2.0,100000.0,1.0,1),
    )
    con.execute(
        "INSERT INTO observation_snapshots(run_id,ts,venue,symbol,price,spread_bps,depth_usd_25bps,data_quality,observation_eligible) VALUES(?,?,?,?,?,?,?,?,?)",
        ("r2",1300.5,"kraken","BTC/USD",101.0,2.0,100000.0,1.0,1),
    )
    con.commit()
    con.close()

    ledger_path=tmp_path/"books.db"
    ledger=Phase13BookLedger(ledger_path)
    try:
        row=Phase13ForecastBookRow(
            freeze_id="p13f_test",book_id="FULL_HIVE_FROZEN",
            world_state_id="w1",world_state_hash="sha256:"+"a"*64,
            symbol="BTC/USD",timestamp_ms=1_000_000,horizon_seconds=300,
            model_id="breakout_continuation_v1",direction="UP",abstain=False,
            probability_positive_net=.6,expected_move_bps=100.0,
            expected_cost_bps=10.0,expected_net_bps=90.0,envelope_id=None,
            entry_price=100.0,regime="test",
        )
        assert ledger.persist_forecasts([row])==1
    finally:
        ledger.close()

    result=settle_mature_phase13_books(
        freeze_id="p13f_test",
        ledger_path=ledger_path,
        market_db_path=market,
        as_of_ts=1400.0,
        tolerance_sec=60.0,
    )
    assert result["settled"]==1
    assert result["errors"]==[]
    rows=result["settlement_book"]["rows"]
    assert len(rows)==1
    assert rows[0]["filled"] is True
    assert rows[0]["realized_net_bps"] is not None
    assert rows[0]["book_id"]=="FULL_HIVE_FROZEN"
