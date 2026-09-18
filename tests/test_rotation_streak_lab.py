from __future__ import annotations

import sqlite3
from pathlib import Path

from agents.nurse import NurseAgent
from scripts.run_live_rotation_streak_lab import (
    LEARNING_AUTHORITY,
    MUTATIONS,
    STABLE,
    Wallet,
)


def test_rotation_authority_and_mutations():
    assert STABLE == "USD_STABLE_REFUGE"
    assert LEARNING_AUTHORITY == "research_evidence_only_no_execution_or_promotion_authority"
    assert set(MUTATIONS) == {
        "stable_control",
        "rotation_naive",
        "rotation_hysteresis",
        "rotation_swarm_hysteresis",
    }
    wallet = Wallet(1000.0)
    assert wallet.position is None
    assert wallet.cash == 1000.0


def test_rotation_source_has_no_private_execution_calls():
    source = Path("scripts/run_live_rotation_streak_lab.py").read_text(encoding="utf-8")
    forbidden = (
        ".create_order(",
        ".fetch_balance(",
        "HIVENANCE_PHASE6_LIVE_SUBMISSION",
        "apiKey",
        "apiSecret",
        "private_key",
    )
    for token in forbidden:
        assert token not in source


def test_nurse_reads_rotation_learning_without_promotion(tmp_path):
    db = tmp_path / "rotation.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE rotation_runs(
          run_id TEXT PRIMARY KEY, started_ts REAL, ended_ts REAL, status TEXT,
          authority TEXT, learning_authority TEXT, config_json TEXT);
        CREATE TABLE rotation_legs(
          leg_id TEXT PRIMARY KEY, run_id TEXT, mutation_id TEXT, symbol TEXT,
          status TEXT, entry_ts REAL, exit_ts REAL, entry_price REAL,
          exit_price REAL, notional_usd REAL, entry_cost_usd REAL,
          exit_cost_usd REAL, net_pnl_usd REAL, net_return_bps REAL,
          duration_sec REAL, entry_score_bps REAL, exit_score_bps REAL,
          entry_regime TEXT, exit_regime TEXT, exit_reason TEXT,
          entry_context_json TEXT, exit_context_json TEXT);
        CREATE TABLE rotation_learning_crystals(
          crystal_id TEXT PRIMARY KEY, run_id TEXT, mutation_id TEXT,
          leg_id TEXT, crystal_family TEXT, scope_key TEXT, symbol TEXT,
          regime TEXT, evidence_strength REAL, net_return_bps REAL,
          duration_sec REAL, authority TEXT, promotion_state TEXT,
          payload_json TEXT, created_ts REAL);
        CREATE TABLE rotation_decisions(
          run_id TEXT, mutation_id TEXT, ts REAL, current_asset TEXT,
          leader_asset TEXT, action TEXT, leader_score_bps REAL,
          incumbent_score_bps REAL, advantage_bps REAL, reason TEXT);
        """
    )
    conn.execute(
        "INSERT INTO rotation_runs VALUES (?,?,?,?,?,?,?)",
        ("r1", 1.0, 2.0, "COMPLETE", "paper", LEARNING_AUTHORITY, "{}"),
    )
    conn.execute(
        "INSERT INTO rotation_legs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "l1","r1","rotation_hysteresis","DOGE/USD","CLOSED",
            1.0,2.0,1.0,1.01,25.0,0.01,0.01,0.23,92.0,1.0,
            12.0,2.0,"bursty","mixed","challenger_clears_switch_hurdle",
            '{"score":{"rebound":true}}',"{}",
        ),
    )
    conn.execute(
        "INSERT INTO rotation_learning_crystals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "c1","r1","rotation_hysteresis","l1","positive_capability",
            "scope","DOGE/USD","bursty",0.8,92.0,1.0,
            LEARNING_AUTHORITY,"candidate_learning_memory_not_promoted","{}",2.0,
        ),
    )
    conn.execute(
        "INSERT INTO rotation_decisions VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("r1","rotation_hysteresis",1.0,STABLE,"DOGE/USD","ENTER",12.0,0.0,12.0,"test"),
    )
    conn.commit()
    conn.close()

    review = NurseAgent().review_rotation_lab(str(db), "r1")
    assert review["run_status"] == "COMPLETE"
    assert review["closed_legs"] == 1
    assert review["positive_candidate_crystals"] == 1
    assert review["negative_candidate_crystals"] == 0
    assert review["rebound_after_retrace"]["samples"] == 1
    assert review["promotion_state"] == "NOT_PROMOTED"
