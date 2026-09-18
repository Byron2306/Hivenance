from __future__ import annotations

import sqlite3
from pathlib import Path

from agents.nurse import NurseAgent
from scripts.run_live_relative_drizzle_lab import (
    LEARNING_AUTHORITY,
    MUTATIONS,
    PairState,
)


def test_relative_pair_state_detects_relative_rebound():
    pair=PairState()
    # Challenger gets progressively cheaper versus incumbent, then turns upward.
    for ratio in (1.0000,0.9990,0.9980,0.9970,0.9960,0.9950,0.9940,0.9930,0.9920,0.9910):
        pair.ratios.append(ratio)
    assert pair.zscore(10) < 0
    assert pair.drawdown_bps(10) < 0
    before=pair.ratios[-1]
    pair.ratios.append(before*1.001)
    assert pair.ret_bps(1) > 0


def test_relative_drizzle_has_expected_mutations_and_research_authority():
    assert set(MUTATIONS)=={
        "relative_naive",
        "relative_streak",
        "relative_hysteresis",
        "relative_swarm_hysteresis",
    }
    assert LEARNING_AUTHORITY=="research_evidence_only_no_execution_or_promotion_authority"


def test_relative_drizzle_source_has_no_private_execution():
    source=Path("scripts/run_live_relative_drizzle_lab.py").read_text(encoding="utf-8")
    for token in (
        ".create_order(",
        ".fetch_balance(",
        "HIVENANCE_PHASE6_LIVE_SUBMISSION",
        "apiKey",
        "apiSecret",
        "private_key",
    ):
        assert token not in source


def test_nurse_attributes_learning_to_entry_transition(tmp_path):
    db=tmp_path/"relative.db"
    conn=sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE relative_runs(
          run_id TEXT PRIMARY KEY,started_ts REAL,ended_ts REAL,status TEXT,
          schema TEXT,authority TEXT,learning_authority TEXT,config_json TEXT);
        CREATE TABLE relative_wallet_marks(
          run_id TEXT,mutation_id TEXT,ts REAL,held_asset TEXT,total_equity_usd REAL,
          sleeve_value_usd REAL,reserve_cash_usd REAL,cumulative_cost_usd REAL,
          switches INTEGER,actions INTEGER,cycle_latency_ms REAL);
        CREATE TABLE relative_legs(
          leg_id TEXT PRIMARY KEY,run_id TEXT,mutation_id TEXT,symbol TEXT,status TEXT,
          entry_ts REAL,exit_ts REAL,entry_price_usd REAL,exit_price_usd REAL,
          entry_value_usd REAL,exit_value_usd REAL,entry_cost_usd REAL,exit_cost_usd REAL,
          net_pnl_usd REAL,net_return_bps REAL,duration_sec REAL,exit_reason TEXT,
          entry_context_json TEXT,exit_context_json TEXT);
        CREATE TABLE relative_learning_crystals(
          crystal_id TEXT PRIMARY KEY,run_id TEXT,mutation_id TEXT,leg_id TEXT,
          crystal_family TEXT,scope_key TEXT,symbol TEXT,evidence_strength REAL,
          net_return_bps REAL,duration_sec REAL,cheapness_z REAL,streak_persistence REAL,
          authority TEXT,promotion_state TEXT,payload_json TEXT,created_ts REAL);
        CREATE TABLE relative_decisions(
          run_id TEXT,mutation_id TEXT,ts REAL,incumbent TEXT,challenger TEXT,action TEXT,
          gross_edge_bps REAL,net_edge_bps REAL,cheapness_z REAL,streak_persistence REAL,
          reason TEXT,context_json TEXT);
        """
    )
    conn.execute(
        "INSERT INTO relative_runs VALUES (?,?,?,?,?,?,?,?)",
        ("r1",1.0,2.0,"COMPLETE","schema","paper",LEARNING_AUTHORITY,'{"start_usd":1000}')
    )
    conn.execute(
        "INSERT INTO relative_wallet_marks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("r1","relative_hysteresis",2.0,"LIQUIDATED",1000.10,0.0,1000.10,0.02,1,3,10.0)
    )
    conn.execute(
        "INSERT INTO relative_legs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "l1","r1","relative_hysteresis","DOGE/USD","CLOSED",
            1.0,2.0,0.08,0.081,25.0,25.10,0.01,0.01,0.10,40.0,1.0,
            "relative_switch",
            '{"type":"relative_switch","from_symbol":"SOL/USD","pair_score":{"cheapness_z":-0.8,"persistence":0.75}}',
            '{"challenger":"AVAX/USD"}'
        )
    )
    conn.execute(
        "INSERT INTO relative_learning_crystals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "c1","r1","relative_hysteresis","l1","positive_capability",
            "relative_hysteresis|SOL/USD->DOGE/USD","DOGE/USD",0.8,40.0,1.0,
            -0.8,0.75,LEARNING_AUTHORITY,"candidate_learning_memory_not_promoted",
            '{"from_symbol":"SOL/USD","to_symbol":"DOGE/USD"}',2.0
        )
    )
    conn.execute(
        "INSERT INTO relative_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("r1","relative_hysteresis",1.0,"SOL/USD","DOGE/USD","SWITCH",12.0,4.0,-0.8,0.75,"test","{}")
    )
    conn.commit()
    conn.close()

    review=NurseAgent().review_relative_drizzle_lab(str(db),"r1")
    assert review["run_status"]=="COMPLETE"
    assert review["positive_candidate_crystals"]==1
    transitions={row["key"]:row for row in review["by_transition"]}
    assert "SOL/USD->DOGE/USD" in transitions
    assert transitions["SOL/USD->DOGE/USD"]["mean_net_return_bps"]==40.0
    assert review["promotion_state"]=="NOT_PROMOTED"
