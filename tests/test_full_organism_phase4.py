from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from strategies.relative_value_lab.selection_regret import (
    freeze_selector_universe,
    settle_mature_selector_freezes,
    selector_regret_report,
    FROZEN_FOLLOW_PROTOCOL,
    collect_frozen_selector_follow_tape,
    settle_selector_follow_cohort,
    selector_regret_report_v3,
)


class Store:
    def __init__(self):
        self.conn=sqlite3.connect(":memory:")
        self._lock=threading.RLock()
        self.conn.execute("""
        CREATE TABLE observation_runs(
            run_id TEXT PRIMARY KEY,
            started_ts REAL,
            completed_ts REAL,
            venue TEXT,
            status TEXT,
            symbols_attempted INTEGER,
            symbols_successful INTEGER,
            symbols_eligible INTEGER,
            mean_data_quality REAL,
            error_count INTEGER,
            dataset_hash TEXT,
            execution_wired INTEGER DEFAULT 0,
            orders_submitted INTEGER DEFAULT 0,
            payload TEXT
        )""")
        self.conn.execute("""
        CREATE TABLE observation_universe_snapshots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, ts REAL, venue TEXT, symbol TEXT, price REAL,
            quote_volume_24h REAL, spread_bps REAL, depth_usd_25bps REAL,
            volatility_expansion REAL, volume_zscore REAL, book_imbalance REAL,
            data_quality REAL, observation_eligible INTEGER,
            selected_for_phase2 INTEGER, comparison_rank INTEGER,
            execution_eligible INTEGER DEFAULT 0, rejection_reasons TEXT, payload TEXT
        )""")
        self.conn.commit()


def _row(symbol:str,rank:int,selected:bool,price:float,score:float,root_char:str,regime:str="trend_expansion"):
    root="sha256:"+root_char*64
    return {
        "symbol":symbol,"venue":"kraken","timestamp_ms":1_000_000,
        "price":price,"spread_bps":2.0,"depth_usd_25bps":100000.0,
        "data_quality":1.0,"score":score,"comparison_rank":rank,
        "selected_for_phase2":selected,"rejection_reasons":[],
        "values":{
            "regime_inputs":{"regime_hint":regime},
            "canonical_world_binding":{
                "canonical_world_state_id":"ws_"+root_char*8,
                "canonical_world_state_hash":root,
                "feature_memory_line_id":root,
            },
        },
    }


def _future(store:Store,symbol:str,ts:float,price:float,spread:float=2.0,depth:float=100000.0):
    run_id=f"future-{symbol}-{int(ts)}"
    store.conn.execute(
        """INSERT OR REPLACE INTO observation_runs
        (run_id,started_ts,completed_ts,venue,status,symbols_attempted,symbols_successful,
         symbols_eligible,mean_data_quality,error_count,dataset_hash,execution_wired,orders_submitted,payload)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id,ts-1.0,ts,"kraken","HEALTHY",1,1,1,1.0,0,"x",0,0,"{}"),
    )
    store.conn.execute(
        """INSERT INTO observation_universe_snapshots
        (run_id,ts,venue,symbol,price,quote_volume_24h,spread_bps,depth_usd_25bps,
         volatility_expansion,volume_zscore,book_imbalance,data_quality,
         observation_eligible,selected_for_phase2,comparison_rank,execution_eligible,
         rejection_reasons,payload)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id,ts-60.0,"kraken",symbol,price,1e8,spread,depth,1.0,0.0,0.0,1.0,1,0,0,0,"[]","{}"),
    )
    store.conn.commit()


def test_phase4_freezes_selected_and_rejected_before_outcome():
    store=Store()
    universe=[
        _row("BTC/USD",1,True,100.0,.9,"a"),
        _row("ETH/USD",2,True,100.0,.8,"b"),
        _row("SOL/USD",3,False,100.0,.7,"c"),
        _row("XRP/USD",4,False,100.0,.6,"d"),
    ]
    summary=freeze_selector_universe(
        store=store,run_id="r1",comparison_universe=universe,
        observed_at_ms=1_000_000,shortlist_size=2,horizon_seconds=300,
        taker_fee_bps_per_side=20.0,
    )
    assert summary["created"]==4
    assert summary["selected_n"]==2
    assert summary["rejected_n"]==2
    rows=store.conn.execute(
        "SELECT selected,target_ts,payload FROM full_organism_selector_freezes ORDER BY selector_rank"
    ).fetchall()
    assert [r[0] for r in rows]==[1,1,0,0]
    assert all(float(r[1])==1300.0 for r in rows)
    assert all(json.loads(r[2])["execution_eligible"] is False for r in rows)


def test_phase4_settles_selected_and_rejected_on_same_future_tape():
    store=Store()
    universe=[
        _row("BTC/USD",1,True,100.0,.9,"a"),
        _row("ETH/USD",2,False,100.0,.4,"b"),
    ]
    freeze_selector_universe(
        store=store,run_id="r1",comparison_universe=universe,
        observed_at_ms=1_000_000,shortlist_size=1,horizon_seconds=300,
        taker_fee_bps_per_side=20.0,
    )
    _future(store,"BTC/USD",1301.0,101.0)
    _future(store,"ETH/USD",1301.0,103.0)
    out=settle_mature_selector_freezes(store=store,now_ts=1400.0,tolerance_sec=30)
    assert out["settled"]==2
    report=selector_regret_report(store,run_id="r1")
    assert report["selected_n"]==1
    assert report["rejected_n"]==1
    # ETH moved further after identical friction, so selector regret is measurable.
    assert report["selected_minus_rejected_bps"] < 0
    assert report["missed_opportunity_rate"] >= 0.5


def test_phase4_selector_score_is_frozen_not_outcome_derived():
    store=Store()
    universe=[
        _row("A/USD",1,True,100.0,.95,"a"),
        _row("B/USD",2,False,100.0,.10,"b"),
    ]
    freeze_selector_universe(
        store=store,run_id="r2",comparison_universe=universe,
        observed_at_ms=1_000_000,shortlist_size=1,horizon_seconds=300,
        taker_fee_bps_per_side=20.0,
    )
    before=store.conn.execute(
        "SELECT symbol,selector_score FROM full_organism_selector_freezes ORDER BY selector_rank"
    ).fetchall()
    _future(store,"A/USD",1301.0,90.0)
    _future(store,"B/USD",1301.0,110.0)
    settle_mature_selector_freezes(store=store,now_ts=1400.0,tolerance_sec=30)
    after=store.conn.execute(
        "SELECT symbol,selector_score FROM full_organism_selector_freezes ORDER BY selector_rank"
    ).fetchall()
    assert before==after


def test_phase4_coinselector_has_independent_blind_selection_mask():
    store=Store()
    universe=[
        _row(f"S{i}/USD",i,i<=3,100.0,1.0-i/10.0,chr(96+i))
        for i in range(1,9)
    ]
    freeze_selector_universe(
        store=store,run_id="r3",comparison_universe=universe,
        observed_at_ms=1_000_000,shortlist_size=3,horizon_seconds=300,
        taker_fee_bps_per_side=20.0,
    )
    rows=store.conn.execute(
        "SELECT symbol,selected,blind_selected,selector_rank,blind_rank FROM full_organism_selector_freezes"
    ).fetchall()
    assert sum(int(r[1]) for r in rows)==3
    assert sum(int(r[2]) for r in rows)==3
    assert any(int(r[1])!=int(r[2]) for r in rows)


def test_phase4_settlement_uses_custody_clock_not_market_candle_clock():
    store=Store()
    universe=[_row("BTC/USD",1,True,100.0,.9,"a")]
    freeze_selector_universe(
        store=store,run_id="r-clock",comparison_universe=universe,
        observed_at_ms=1_000_000,shortlist_size=1,horizon_seconds=300,
        taker_fee_bps_per_side=20.0,
    )
    # Market timestamp is deliberately stale, but custody time is after target.
    _future(store,"BTC/USD",1301.0,102.0)
    out=settle_mature_selector_freezes(store=store,now_ts=1400.0,tolerance_sec=30)
    assert out["settled"]==1
    raw=store.conn.execute(
        "SELECT payload FROM full_organism_selector_settlements_v2"
    ).fetchone()[0]
    payload=json.loads(raw)
    assert payload["settlement_clock"]=="OBSERVATION_RUN_COMPLETED_TS"
    assert payload["exit_custody_ts"]==1301.0
    assert payload["exit_market_ts"]==1241.0


class FollowClient:
    def __init__(self):
        self.prices={"BTC/USD":101.0,"ETH/USD":103.0}
    def fetch_tickers(self):
        return {s:{"last":p} for s,p in self.prices.items()}
    def fetch_ticker(self,symbol):
        return {"last":self.prices[symbol]}
    def fetch_order_book(self,symbol,limit=50):
        p=self.prices[symbol]
        return {"bids":[[p-.01,1000.0]],"asks":[[p+.01,1000.0]]}


def test_phase4_frozen_follow_protocol_settles_exact_original_symbols():
    store=Store()
    universe=[
        _row("BTC/USD",1,True,100.0,.9,"a"),
        _row("ETH/USD",2,False,100.0,.4,"b"),
    ]
    freeze_selector_universe(
        store=store,run_id="follow1",comparison_universe=universe,
        observed_at_ms=1_000_000,shortlist_size=1,horizon_seconds=300,
        taker_fee_bps_per_side=20.0,maturation_protocol=FROZEN_FOLLOW_PROTOCOL,
    )
    follow=collect_frozen_selector_follow_tape(
        store=store,client=FollowClient(),cohort_run_id="follow1",now_ts=1301.0,
    )
    assert follow["symbols_attempted"]==2
    assert follow["symbols_successful"]==2
    settled=settle_selector_follow_cohort(
        store=store,cohort_run_id="follow1",now_ts=1302.0,tolerance_sec=30.0,
    )
    assert settled["settled"]==2
    assert settled["deferred"]==0
    report=selector_regret_report_v3(store,run_id="follow1")
    assert report["settled_n"]==2
    assert report["selected_n"]==1
    assert report["rejected_n"]==1
    assert report["maturation_protocol"]==FROZEN_FOLLOW_PROTOCOL
