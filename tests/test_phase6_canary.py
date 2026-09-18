from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.canary_lab import (
    PHASE6_ACKNOWLEDGEMENT,
    TinyLiveCanary,
    build_canary_approval,
    phase6_spot_freeze_compatibility,
)
from strategies.volatility_breakout.canary_store import CanaryStore
from strategies.volatility_breakout.shadow_flight import frozen_config_hash


class ReadyStore(DataStoreAgent):
    def __init__(self, path: str, now: float):
        super().__init__(path)
        self.now = now
        self.freeze = {
            "freeze_id": "freeze-phase5",
            "phase4_run_id": "phase4-run",
            "candidate_key": "breakout_continuation_v1::marketable_limit",
            "model_id": "breakout_continuation_v1",
            "order_policy": "marketable_limit",
            "symbol": "ETH/USD",
            "direction": "UP",
            "approved_by": "Byron",
            "approved_ts": now - 100,
            "phase4_dataset_hash": "phase4-hash",
            "config_hash": "",
            "status": "ACTIVE",
        }

    def get_phase5_active_freeze(self):
        return dict(self.freeze)

    def get_phase5_readiness(self, **kwargs):
        return {
            "phase": 5,
            "ready_for_phase6_review": True,
            "execution_eligible": False,
            "transmission_attempts": 0,
            "real_orders_submitted": 0,
            "reasons": [],
        }


class FakeKraken:
    def __init__(self):
        self.validate_calls = 0
        self.add_calls = 0
        self.deadman_calls = 0
        self.orders = {}
        self.open = {}
        self.raise_on_add = False
        self.external_open = False

    def api_key_info(self):
        return {"permissions": ["Orders and trades - Create & modify orders", "Orders and trades - Query open orders & trades"]}

    def system_status(self):
        return {"status": "online"}

    def asset_pairs(self, pair):
        return {
            "XETHZUSD": {
                "altname": "ETHUSD",
                "pair_decimals": 2,
                "lot_decimals": 6,
                "ordermin": "0.001",
                "costmin": "1.0",
                "status": "online",
            }
        }

    def balances(self):
        return {"ZUSD": "100.0", "XETH": "0.0"}

    def open_orders(self):
        payload = dict(self.open)
        if self.external_open:
            payload["external-1"] = {"cl_ord_id": "manual-order", "status": "open"}
        return {"open": payload}

    def validate_order(self, payload):
        self.validate_calls += 1
        return {"descr": {"order": "validated"}}

    def add_order(self, payload):
        self.add_calls += 1
        if self.raise_on_add:
            raise TimeoutError("simulated ambiguous timeout")
        txid = f"TX{self.add_calls}"
        qty = float(payload["volume"])
        price = float(payload["price"])
        self.orders[txid] = {
            "status": "closed",
            "vol": str(qty),
            "vol_exec": str(qty),
            "cost": str(qty * price),
            "fee": "0.01",
            "price": str(price),
            "cl_ord_id": payload["cl_ord_id"],
        }
        return {"txid": [txid], "descr": {"order": "accepted"}}

    def query_orders(self, txids):
        return {txid: self.orders[txid] for txid in txids if txid in self.orders}

    def cancel_all_after(self, timeout_sec):
        self.deadman_calls += 1
        return {"currentTime": "now", "triggerTime": "later", "timeout": timeout_sec}

    def cancel_all(self):
        self.open.clear()
        return {"count": 0}


def cfg() -> SimpleNamespace:
    return SimpleNamespace(
        exchange="kraken",
        symbol="ETH/USD",
        phase6_canary_enabled=True,
        phase6_live_submission_enabled=True,
        phase6_allowed_symbols=["ETH/USD"],
        phase6_max_notional_usd=5.0,
        phase6_max_entry_orders_per_approval=1,
        phase6_approval_lease_sec=900,
        phase6_candidate_max_age_sec=30,
        phase6_market_data_max_age_sec=10,
        phase6_min_data_quality=0.99,
        phase6_max_spread_bps=30.0,
        phase6_max_slippage_bps=40.0,
        phase6_stop_distance_bps=250.0,
        phase6_target_distance_bps=400.0,
        phase6_deadman_timeout_sec=60,
        phase6_require_isolated_account=True,
        phase6_min_phase7_round_trips=50,
        phase5_readiness_min_distinct_days=30,
        phase5_readiness_min_settled=100,
        phase5_readiness_max_cost_mae_bps=20.0,
        phase5_readiness_min_fill_ratio=0.5,
        phase5_readiness_require_positive_mean=True,
        phase2_horizons_seconds=[300],
        phase2_min_data_quality=0.99,
        phase2_minimum_edge_multiple=2.0,
        phase2_breakout_min_expansion=1.5,
        phase2_breakout_min_volume_zscore=1.0,
        phase2_breakout_min_return_zscore=1.0,
        phase2_reversion_min_stretch_zscore=2.0,
        phase2_reversion_min_range_extreme=0.9,
        phase3_simulated_equity_usd=1000.0,
        phase3_risk_fraction=0.0005,
        phase3_sleeve_fraction=0.02,
        phase3_max_notional_usd=25.0,
        phase3_max_depth_participation=0.01,
        phase3_min_notional_usd=5.0,
        phase3_maker_fee_bps=10.0,
        phase3_taker_fee_bps=20.0,
        phase3_max_entry_spread_bps=60.0,
        phase5_shadow_reference_notional_usd=10.0,
        phase5_shadow_stop_distance_bps=250.0,
        phase5_shadow_max_intents_per_cycle=25,
        phase5_shadow_chase_timeout_sec=30,
        phase5_shadow_entry_latency_ms=250.0,
    )


def rapid_paper_cfg() -> SimpleNamespace:
    config = cfg()
    config.symbol = "ONDO/USD"
    config.phase6_live_submission_enabled = False
    config.phase6_rapid_paper_canary_enabled = True
    config.phase6_allowed_symbols = ["ONDO/USD"]
    config.phase6_allowed_directions = ["UP", "DOWN"]
    config.phase6_rapid_candidate_max_age_sec = 300
    config.phase6_min_data_quality = 0.5
    config.phase6_max_spread_bps = 120.0
    return config


def seed(store: ReadyStore, now: float, *, price: float = 100.0, run_id: str = "obs-now") -> None:
    with store._lock:
        store.conn.execute(
            """INSERT OR REPLACE INTO observation_snapshots
            (run_id,ts,venue,symbol,price,quote_volume_24h,spread_bps,depth_usd_25bps,
             volatility_expansion,volume_zscore,book_imbalance,data_quality,
             observation_eligible,execution_eligible,rejection_reasons,payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, now, "kraken", "ETH/USD", price, 100_000_000.0, 4.0, 500_000.0,
             1.8, 2.0, 0.2, 1.0, 1, 0, "[]", json.dumps({"price": price, "ts": now, "data_quality": 1.0, "spread_bps": 4.0})),
        )
        store.conn.execute(
            """INSERT OR REPLACE INTO phase5_shadow_intents
            (shadow_intent_id,forecast_id,freeze_id,phase4_run_id,candidate_key,model_id,order_policy,
             venue,symbol,direction,side,order_type,time_in_force,quantity,notional_usd,reference_price,
             limit_price,stop_distance_bps,risk_budget_usd,predicted_move_bps,predicted_cost_bps,
             predicted_net_bps,probability_positive_net,horizon_seconds,created_ts,target_ts,data_quality,
             spread_bps,depth_usd_25bps,venue_profile_version,config_hash,status,transmission_status,
             private_endpoint_called,credentials_used,transmission_attempted,settled,execution_wired,
             live_eligible,real_orders_submitted,payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("shadow-live", "forecast-live", "freeze-phase5", "phase4-run",
             "breakout_continuation_v1::marketable_limit", "breakout_continuation_v1", "marketable_limit",
             "kraken", "ETH/USD", "UP", "buy", "limit", "IOC", 0.05, 5.0, price,
             price * 1.001, 250.0, 0.5, 100.0, 20.0, 80.0, 0.7, 300, now, now + 300,
             1.0, 4.0, 500_000.0, "kraken-v1", "shadow-config", "PENDING",
             "NEVER_TRANSMITTED", 0, 0, 0, 0, 0, 0, 0, "{}"),
        )
        store.conn.commit()


def seed_small_window_tape(
    store: ReadyStore,
    now: float,
    *,
    symbol: str = "ONDO/USD",
    direction: str = "DOWN",
    target_ts: float | None = None,
    trade_id: str = "rapid-down-1",
    source_id: str = "rapid-source-1",
    health_score: float | None = None,
    signal_lane: str = "continuation",
    window_sec: int = 1800,
    status: str = "OPEN",
    net_return_bps: float | None = None,
    positive_net: bool | None = None,
    expected_net_bps: float = 120.0,
    expected_cost_bps: float = 20.0,
    same_direction_windows: list[int] | None = None,
) -> None:
    target = float(target_ts if target_ts is not None else now + 180)
    with store._lock:
        store.conn.execute("""
            CREATE TABLE IF NOT EXISTS rapid_paper_tape_trades (
                trade_id TEXT PRIMARY KEY,
                source_forecast_id TEXT UNIQUE,
                run_id TEXT,
                venue TEXT,
                symbol TEXT,
                model_id TEXT,
                hypothesis TEXT,
                direction TEXT,
                status TEXT,
                entry_ts REAL,
                target_ts REAL,
                settled_ts REAL,
                updated_ts REAL,
                entry_price REAL,
                exit_price REAL,
                notional_usd REAL,
                expected_net_bps REAL,
                expected_cost_bps REAL,
                probability_positive_net REAL,
                gross_return_bps REAL,
                directional_return_bps REAL,
                net_return_bps REAL,
                positive_net INTEGER,
                llm_status TEXT,
                llm_veto INTEGER,
                llm_risks TEXT,
                failure_reason TEXT,
                payload TEXT
            )
        """)
        payload = {
            "candidate": {
                "symbol": symbol,
                "direction": direction,
                "signal_lane": signal_lane,
                "window_sec": window_sec,
                "window_label": {60: "1m", 300: "5m", 1800: "30m", 3600: "1h"}.get(window_sec, f"{window_sec}s"),
                "same_direction_windows": same_direction_windows or [window_sec],
                "latest_observation": {
                    "price": 0.74,
                    "data_quality": 0.8,
                    "spread_bps": 20.0,
                },
            }
        }
        if health_score is not None:
            payload["candidate"]["health_score"] = health_score
            payload["candidate"]["health_state"] = "HEALTHY"
        store.conn.execute(
            """
            INSERT OR REPLACE INTO rapid_paper_tape_trades
            (trade_id, source_forecast_id, run_id, venue, symbol, model_id, hypothesis, direction,
             status, entry_ts, target_ts, updated_ts, entry_price, notional_usd, expected_net_bps,
             expected_cost_bps, probability_positive_net, net_return_bps, positive_net, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trade_id,
                source_id,
                "rapid-run",
                "kraken",
                symbol,
                "small_window_trend_comparison_v1",
                "recent_delta_volatility",
                direction,
                status,
                now,
                target,
                now,
                0.74,
                0.5,
                expected_net_bps,
                expected_cost_bps,
                0.65,
                net_return_bps,
                None if positive_net is None else int(bool(positive_net)),
                json.dumps(payload),
            ),
        )
        store.conn.commit()


def approve(store: ReadyStore, config: SimpleNamespace, now: float):
    store.freeze["config_hash"] = frozen_config_hash(config)
    approval = build_canary_approval(
        store,
        config,
        approved_by="Byron",
        acknowledgement=PHASE6_ACKNOWLEDGEMENT,
        approved_ts=now,
    )
    CanaryStore(store).persist_approval(approval.to_dict())
    return approval


def test_phase6_approval_rejects_incompatible_spot_freeze(tmp_path: Path):
    now = 1_900_000_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "incompatible-approval.db"), now)
    store.freeze.update({
        "candidate_key": "model_id=breakout_continuation_v1::order_policy=marketable_limit::symbol=SOL/USD::direction=DOWN",
        "symbol": "SOL/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    with pytest.raises(ValueError, match="not Phase-6 canary-compatible"):
        build_canary_approval(
            store,
            config,
            approved_by="Byron",
            acknowledgement=PHASE6_ACKNOWLEDGEMENT,
            approved_ts=now,
        )


def test_phase6_snapshot_explains_incompatible_freeze(tmp_path: Path):
    now = 1_900_000_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "incompatible-snapshot.db"), now)
    store.freeze.update({
        "candidate_key": "model_id=breakout_continuation_v1::order_policy=marketable_limit::symbol=SOL/USD::direction=DOWN",
        "symbol": "SOL/USD",
        "direction": "DOWN",
    })
    snapshot = TinyLiveCanary(config, store, FakeKraken(), now_fn=lambda: now, live_interlock=False).snapshot()
    preflight = snapshot["preflight"]
    assert preflight["ready_to_attempt_entry_probe"] is False
    assert "phase5_freeze_symbol_not_phase6_allowlisted" in preflight["reasons"]
    assert "phase5_freeze_direction_not_spot_long_canary" in preflight["reasons"]
    assert preflight["freeze_compatibility"]["authority"] == "kraken_spot_long_only_tiny_canary"


def test_phase6_rapid_paper_canary_accepts_small_window_down_without_private_client(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    store = ReadyStore(str(tmp_path / "rapid-paper-down.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(store, now, symbol="ONDO/USD", direction="DOWN")

    compatibility = phase6_spot_freeze_compatibility(store.get_phase5_active_freeze(), config)
    assert compatibility["canary_compatible"] is True
    assert compatibility["authority"] == "paper_small_window_directional_canary"
    assert compatibility["allowed_directions"] == ["DOWN", "UP"]

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["mode"] == "rapid_paper_canary"
    assert result["live_submission_attempts"] == 0
    assert result["live_orders_submitted"] == 0
    assert result["canary_intent"]["side"] == "paper_sell"
    assert store.conn.execute("SELECT COUNT(*) FROM phase6_canary_intents").fetchone()[0] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM phase6_canary_orders").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_phase6_rapid_paper_canary_promotes_fresh_healthy_dynamic_symbol(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_min_health_score = 45.0
    store = ReadyStore(str(tmp_path / "rapid-paper-dynamic.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 10,
        symbol="BLESS/USD",
        direction="DOWN",
        trade_id="rapid-bless-1",
        source_id="rapid-source-bless",
        health_score=72.0,
    )

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["canary_intent"]["symbol"] == "BLESS/USD"
    assert result["canary_intent"]["side"] == "paper_sell"
    assert result["source_trade_id"] == "rapid-bless-1"


def test_phase6_rapid_dynamic_freeze_symbol_can_be_outside_static_allowlist(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_allowed_symbols = ["ONDO/USD"]
    store = ReadyStore(str(tmp_path / "rapid-paper-dynamic-freeze.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|BLESS/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "BLESS/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })

    compatibility = phase6_spot_freeze_compatibility(store.get_phase5_active_freeze(), config)

    assert compatibility["canary_compatible"] is True
    assert compatibility["authority"] == "paper_small_window_directional_canary"


def test_phase6_rapid_paper_canary_skips_negative_memory_slice(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_block_negative_canary_memory_enabled = True
    config.phase6_rapid_negative_memory_min_samples = 1
    store = ReadyStore(str(tmp_path / "rapid-paper-negative-memory.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 10,
        symbol="BLESS/USD",
        direction="DOWN",
        trade_id="rapid-bless-negative-memory",
        source_id="rapid-source-bless-negative-memory",
        health_score=90.0,
    )
    seed_small_window_tape(
        store,
        now - 9,
        symbol="CTSI/USD",
        direction="DOWN",
        trade_id="rapid-ctsi-clean-memory",
        source_id="rapid-source-ctsi-clean-memory",
        health_score=70.0,
    )
    store.persist_crystal_registry_entry({
        "crystal_id": "phase6-memory-loss-bless-down",
        "created_ts": now - 5,
        "updated_ts": now - 5,
        "crystal_family": "small_window_canary_memory",
        "artifact_class": "small_window_canary_memory_crystal",
        "authority": "paper_research_only",
        "verification_state": "observed_settlement",
        "phase_scope": 6,
        "scope_key": "BLESS/USD|DOWN|1800",
        "symbol": "BLESS/USD",
        "venue": "kraken",
        "regime_hint": "small_window_canary",
        "hypothesis": "recent_delta_volatility",
        "world_state_id": None,
        "applicability_hash": "BLESS/USD|DOWN|1800",
        "evidence_strength": 80.0,
        "drift_status": "negative_memory",
        "expires_ts": None,
        "payload": {
            "schema": "small_window_canary_memory_crystal_v1",
            "symbol": "BLESS/USD",
            "direction": "DOWN",
            "window_sec": 1800,
            "positive_net": False,
            "net_return_bps": -80.0,
            "settled_ts": now - 5,
        },
    })

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["canary_intent"]["symbol"] == "CTSI/USD"
    assert result["source_trade_id"] == "rapid-ctsi-clean-memory"


def test_phase6_rapid_paper_canary_requires_tape_slice_edge_floor(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_tape_slice_edge_enabled = True
    config.phase6_rapid_tape_slice_min_samples = 2
    config.phase6_rapid_tape_slice_min_win_rate = 0.45
    config.phase6_rapid_tape_slice_min_mean_net_bps = 0.0
    store = ReadyStore(str(tmp_path / "rapid-paper-tape-floor.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    for index, net_bps in enumerate((-45.0, -20.0), start=1):
        seed_small_window_tape(
            store,
            now - 600 - index,
            symbol="BLESS/USD",
            direction="DOWN",
            trade_id=f"rapid-bless-loss-{index}",
            source_id=f"rapid-source-bless-loss-{index}",
            health_score=90.0,
            signal_lane="continuation",
            status="CLOSED_LOSS",
            net_return_bps=net_bps,
            positive_net=False,
        )
    seed_small_window_tape(
        store,
        now - 5,
        symbol="BLESS/USD",
        direction="DOWN",
        trade_id="rapid-bless-bad-but-hot",
        source_id="rapid-source-bless-bad-but-hot",
        health_score=95.0,
        signal_lane="continuation",
    )
    seed_small_window_tape(
        store,
        now - 4,
        symbol="CTSI/USD",
        direction="DOWN",
        trade_id="rapid-ctsi-exploratory",
        source_id="rapid-source-ctsi-exploratory",
        health_score=70.0,
        signal_lane="continuation",
    )

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["canary_intent"]["symbol"] == "CTSI/USD"
    assert result["source_trade_id"] == "rapid-ctsi-exploratory"


def test_phase6_rapid_paper_canary_can_require_repeatable_tape_slice(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_tape_slice_edge_enabled = True
    config.phase6_rapid_tape_slice_min_samples = 2
    config.phase6_rapid_allow_exploratory_slices = False
    store = ReadyStore(str(tmp_path / "rapid-paper-no-exploratory.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 5,
        symbol="CTSI/USD",
        direction="DOWN",
        trade_id="rapid-ctsi-unproven",
        source_id="rapid-source-ctsi-unproven",
        health_score=90.0,
        signal_lane="continuation",
    )

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "ARMED_WAITING"
    assert result["reasons"] == ["no_fresh_matching_small_window_tape"]
    assert CanaryStore(store).scorecard()["paper_canary_open"] == 0


def test_phase6_rapid_paper_canary_requires_fast_window_and_cost_cushion(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_tape_slice_edge_enabled = False
    config.phase6_rapid_allowed_window_sec = [60, 300]
    config.phase6_rapid_max_cost_bps = 45.0
    config.phase6_rapid_min_expected_net_bps = 35.0
    config.phase6_rapid_min_expected_net_to_cost_ratio = 1.75
    store = ReadyStore(str(tmp_path / "rapid-paper-cost-cushion.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 5,
        symbol="BLESS/USD",
        direction="DOWN",
        trade_id="rapid-bless-long-window",
        source_id="rapid-source-bless-long-window",
        health_score=95.0,
        window_sec=1800,
        expected_net_bps=200.0,
        expected_cost_bps=20.0,
    )
    seed_small_window_tape(
        store,
        now - 4,
        symbol="CTSI/USD",
        direction="DOWN",
        trade_id="rapid-ctsi-expensive",
        source_id="rapid-source-ctsi-expensive",
        health_score=90.0,
        window_sec=300,
        expected_net_bps=120.0,
        expected_cost_bps=70.0,
    )
    seed_small_window_tape(
        store,
        now - 3,
        symbol="ESP/USD",
        direction="DOWN",
        trade_id="rapid-esp-thin-cushion",
        source_id="rapid-source-esp-thin-cushion",
        health_score=85.0,
        window_sec=300,
        expected_net_bps=50.0,
        expected_cost_bps=40.0,
    )
    seed_small_window_tape(
        store,
        now - 2,
        symbol="ZBT/USD",
        direction="DOWN",
        trade_id="rapid-zbt-cost-covered",
        source_id="rapid-source-zbt-cost-covered",
        health_score=70.0,
        window_sec=300,
        expected_net_bps=80.0,
        expected_cost_bps=30.0,
    )

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["canary_intent"]["symbol"] == "ZBT/USD"
    assert result["source_trade_id"] == "rapid-zbt-cost-covered"


def test_phase6_rapid_paper_canary_allows_adjacent_interval_transition(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_tape_slice_edge_enabled = True
    config.phase6_rapid_tape_slice_min_samples = 2
    config.phase6_rapid_tape_slice_min_win_rate = 0.50
    config.phase6_rapid_tape_slice_min_mean_net_bps = 15.0
    config.phase6_rapid_allow_exploratory_slices = False
    config.phase6_rapid_allowed_window_sec = [60, 300]
    config.phase6_rapid_interval_transition_enabled = True
    config.phase6_rapid_interval_transition_pairs = [[60, 300], [300, 1800], [1800, 3600]]
    config.phase6_rapid_max_cost_bps = 45.0
    config.phase6_rapid_min_expected_net_bps = 35.0
    config.phase6_rapid_min_expected_net_to_cost_ratio = 1.75
    store = ReadyStore(str(tmp_path / "rapid-paper-interval-transition.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    for index, net_bps in enumerate((42.0, 61.0), start=1):
        seed_small_window_tape(
            store,
            now - 600 - index,
            symbol="STG/USD",
            direction="DOWN",
            trade_id=f"rapid-stg-transition-win-{index}",
            source_id=f"rapid-source-stg-transition-win-{index}",
            health_score=88.0,
            signal_lane="continuation",
            window_sec=3600,
            status="CLOSED_WIN",
            net_return_bps=net_bps,
            positive_net=True,
            same_direction_windows=[1800, 3600],
        )
    seed_small_window_tape(
        store,
        now - 5,
        symbol="STG/USD",
        direction="DOWN",
        trade_id="rapid-stg-30m-1h-transition",
        source_id="rapid-source-stg-30m-1h-transition",
        health_score=90.0,
        signal_lane="continuation",
        window_sec=3600,
        expected_net_bps=95.0,
        expected_cost_bps=35.0,
        same_direction_windows=[1800, 3600],
    )

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["canary_intent"]["symbol"] == "STG/USD"
    assert result["source_trade_id"] == "rapid-stg-30m-1h-transition"
    assert result["canary_intent"]["payload"]["rapid_paper_trade"]["interval_transition"]["pair"] == "1800->3600"


def test_phase6_rapid_paper_canary_uses_counterfactual_delay_hold_edge(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_tape_slice_edge_enabled = True
    config.phase6_rapid_tape_slice_min_samples = 2
    config.phase6_rapid_allow_exploratory_slices = False
    config.phase6_rapid_allowed_window_sec = [60, 300]
    config.phase6_rapid_interval_transition_enabled = True
    config.phase6_rapid_interval_transition_pairs = [[60, 300], [300, 1800], [1800, 3600]]
    config.phase6_rapid_counterfactual_promotion_enabled = True
    config.phase6_rapid_counterfactual_min_samples = 3
    config.phase6_rapid_counterfactual_min_win_rate = 0.50
    config.phase6_rapid_counterfactual_min_median_net_bps = 0.0
    config.phase6_rapid_lane_min_expected_net_to_cost_ratio = {"micro_reversion": 1.25}
    store = ReadyStore(str(tmp_path / "rapid-paper-counterfactual-edge.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|UP|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "UP",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 35,
        symbol="ZBT/USD",
        direction="UP",
        target_ts=now + 60,
        trade_id="rapid-zbt-delayed-reversion",
        source_id="rapid-source-zbt-delayed-reversion",
        health_score=80.0,
        signal_lane="micro_reversion",
        window_sec=3600,
        expected_net_bps=50.0,
        expected_cost_bps=30.0,
        same_direction_windows=[1800, 3600],
    )
    with store._lock:
        store.conn.execute(
            """
            CREATE TABLE phase6_rapid_gate_audition_counterfactuals (
                counterfactual_id TEXT PRIMARY KEY,
                trade_id TEXT,
                symbol TEXT,
                direction TEXT,
                window_sec INTEGER,
                signal_lane TEXT,
                interval_pair TEXT,
                entry_delay_sec INTEGER,
                hold_sec INTEGER,
                net_return_bps REAL,
                status TEXT
            )
            """
        )
        for index, net_bps in enumerate((25.0, 38.0, -5.0), start=1):
            store.conn.execute(
                """
                INSERT INTO phase6_rapid_gate_audition_counterfactuals
                (counterfactual_id, trade_id, symbol, direction, window_sec, signal_lane,
                 interval_pair, entry_delay_sec, hold_sec, net_return_bps, status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"cf-{index}",
                    f"history-{index}",
                    "ZBT/USD",
                    "UP",
                    3600,
                    "micro_reversion",
                    "1800->3600",
                    30,
                    300,
                    net_bps,
                    "CLOSED_WIN" if net_bps > 0 else "CLOSED_LOSS",
                ),
            )
        store.conn.commit()

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["source_trade_id"] == "rapid-zbt-delayed-reversion"
    edge = result["canary_intent"]["payload"]["counterfactual_edge"]
    assert edge["accepted"] is True
    assert edge["entry_delay_sec"] == 30
    assert edge["hold_sec"] == 300
    assert result["canary_intent"]["horizon_ts"] == now + 300


def test_phase6_rapid_paper_canary_respects_open_cap(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_max_open_canaries = 1
    store = ReadyStore(str(tmp_path / "rapid-paper-open-cap.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 10,
        symbol="BLESS/USD",
        direction="DOWN",
        trade_id="rapid-bless-cap-1",
        source_id="rapid-source-bless-cap-1",
        health_score=72.0,
    )
    seed_small_window_tape(
        store,
        now - 9,
        symbol="CTSI/USD",
        direction="DOWN",
        trade_id="rapid-ctsi-cap-2",
        source_id="rapid-source-ctsi-cap-2",
        health_score=80.0,
    )
    canary = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False)

    first = canary.run_once(live_requested=False)
    second = canary.run_once(live_requested=False)

    assert first["status"] == "PAPER_CANARY_OBSERVED"
    assert second["status"] == "ARMED_WAITING"
    assert "rapid_paper_canary_open_cap_reached" in second["reasons"]
    assert CanaryStore(store).scorecard()["paper_canary_open"] == 1


def test_phase6_rapid_paper_canary_prunes_surplus_open_after_cap_reduction(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_max_open_canaries = 2
    store = ReadyStore(str(tmp_path / "rapid-paper-prune-cap.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 10,
        symbol="BLESS/USD",
        direction="DOWN",
        trade_id="rapid-bless-prune-1",
        source_id="rapid-source-bless-prune-1",
        health_score=90.0,
    )
    seed_small_window_tape(
        store,
        now - 9,
        symbol="CTSI/USD",
        direction="DOWN",
        trade_id="rapid-ctsi-prune-2",
        source_id="rapid-source-ctsi-prune-2",
        health_score=80.0,
    )
    canary = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False)
    canary.run_once(live_requested=False)
    canary.run_once(live_requested=False)

    config.phase6_rapid_max_open_canaries = 1
    pruned = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)
    scorecard = CanaryStore(store).scorecard()

    assert pruned["open_cap_reconciliation"]["pruned"] == 1
    assert pruned["status"] == "ARMED_WAITING"
    assert scorecard["paper_canary_open"] == 1
    assert scorecard["paper_canary_pruned"] == 1
    assert scorecard["paper_canary_losses"] == 0


def test_phase6_rapid_paper_canary_expires_stale_open_slot(tmp_path: Path):
    clock = [1_900_000_000.0]
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_max_open_canaries = 1
    config.phase6_rapid_settlement_tolerance_sec = 10
    config.phase6_rapid_expire_after_sec = 5
    store = ReadyStore(str(tmp_path / "rapid-paper-expire-open-slot.db"), clock[0])
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        clock[0] - 10,
        symbol="BLESS/USD",
        direction="DOWN",
        target_ts=clock[0] + 30,
        trade_id="rapid-bless-expiring",
        source_id="rapid-source-bless-expiring",
        health_score=90.0,
    )
    seed_small_window_tape(
        store,
        clock[0] - 9,
        symbol="CTSI/USD",
        direction="DOWN",
        target_ts=clock[0] + 180,
        trade_id="rapid-ctsi-after-expiry",
        source_id="rapid-source-ctsi-after-expiry",
        health_score=70.0,
    )
    canary = TinyLiveCanary(config, store, None, now_fn=lambda: clock[0], live_interlock=False)

    first = canary.run_once(live_requested=False)
    capped = canary.run_once(live_requested=False)
    clock[0] += 46
    recovered = canary.run_once(live_requested=False)

    scorecard = CanaryStore(store).scorecard()
    assert first["status"] == "PAPER_CANARY_OBSERVED"
    assert capped["status"] == "ARMED_WAITING"
    assert recovered["settlement"]["expired"] == 1
    assert recovered["status"] == "PAPER_CANARY_OBSERVED"
    assert recovered["source_trade_id"] == "rapid-ctsi-after-expiry"
    assert scorecard["paper_canary_expired"] == 1
    assert scorecard["paper_canary_losses"] == 0
    assert scorecard["paper_canary_open"] == 1


def test_phase6_rapid_paper_canary_skips_past_horizon_trade(tmp_path: Path):
    now = 1_900_000_000.0
    config = rapid_paper_cfg()
    config.phase6_rapid_dynamic_symbols_enabled = True
    config.phase6_rapid_min_remaining_horizon_sec = 15.0
    store = ReadyStore(str(tmp_path / "rapid-paper-past-horizon.db"), now)
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(
        store,
        now - 120,
        symbol="BLESS/USD",
        direction="DOWN",
        target_ts=now - 5,
        trade_id="rapid-bless-past-horizon",
        source_id="rapid-source-bless-past-horizon",
        health_score=90.0,
    )
    seed_small_window_tape(
        store,
        now - 5,
        symbol="CTSI/USD",
        direction="DOWN",
        target_ts=now + 30,
        trade_id="rapid-ctsi-future-horizon",
        source_id="rapid-source-ctsi-future-horizon",
        health_score=70.0,
    )

    result = TinyLiveCanary(config, store, None, now_fn=lambda: now, live_interlock=False).run_once(live_requested=False)

    assert result["status"] == "PAPER_CANARY_OBSERVED"
    assert result["canary_intent"]["symbol"] == "CTSI/USD"
    assert result["source_trade_id"] == "rapid-ctsi-future-horizon"


def test_phase6_rapid_paper_canary_settles_same_slice_directional_result(tmp_path: Path):
    clock = [1_900_000_000.0]
    config = rapid_paper_cfg()
    store = ReadyStore(str(tmp_path / "rapid-paper-settle.db"), clock[0])
    store.freeze.update({
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
        "config_hash": frozen_config_hash(config),
    })
    seed_small_window_tape(store, clock[0] - 30, symbol="ONDO/USD", direction="DOWN", target_ts=clock[0] + 60)
    clock[0] += 75
    with store._lock:
        store.conn.execute(
            """INSERT OR REPLACE INTO observation_snapshots
            (run_id,ts,venue,symbol,price,quote_volume_24h,spread_bps,depth_usd_25bps,
             volatility_expansion,volume_zscore,book_imbalance,data_quality,
             observation_eligible,execution_eligible,rejection_reasons,payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "obs-ondo-settle",
                    clock[0],
                    "kraken",
                    "ONDO/USD",
                0.72,
                1_000_000.0,
                5.0,
                100_000.0,
                1.0,
                0.0,
                0.0,
                1.0,
                1,
                0,
                "[]",
                json.dumps({"price": 0.72, "ts": clock[0]}),
            ),
        )
        store.conn.commit()

    clock[0] -= 75
    canary = TinyLiveCanary(config, store, None, now_fn=lambda: clock[0], live_interlock=False)
    observed = canary.run_once(live_requested=False)
    assert observed["status"] == "PAPER_CANARY_OBSERVED"

    clock[0] += 75
    settled = canary.run_once(live_requested=False)

    assert settled["settlement"]["settled"] == 1
    assert settled["settlement"]["wins"] == 1
    receipt = CanaryStore(store).paper_canary_settlements(limit=1)[0]
    assert receipt["status"] == "PAPER_CANARY_WIN"
    assert receipt["side"] == "paper_sell"
    assert receipt["net_return_bps"] > 0
    assert CanaryStore(store).scorecard()["paper_canary_wins"] == 1
    rows = store.get_crystal_registry_rows(crystal_family="small_window_canary_memory", limit=5)
    assert len(rows) == 1
    memory = rows[0]["payload"]
    assert memory["symbol"] == "ONDO/USD"
    assert memory["direction"] == "DOWN"
    assert memory["window_sec"] == 1800
    assert memory["positive_net"] is True
    assert memory["net_return_bps"] > 0


def test_phase6_no_approval_means_no_private_order(tmp_path: Path):
    now = 1_900_000_000.0
    store = ReadyStore(str(tmp_path / "none.db"), now)
    store.freeze["config_hash"] = frozen_config_hash(cfg())
    fake = FakeKraken()
    result = TinyLiveCanary(cfg(), store, fake, now_fn=lambda: now, live_interlock=True).run_once(live_requested=True)
    assert result["status"] == "DISARMED"
    assert fake.add_calls == 0
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_phase6_validate_only_requires_no_live_submission(tmp_path: Path):
    now = 1_900_000_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "validate.db"), now)
    approve(store, config, now - 1)
    seed(store, now)
    fake = FakeKraken()
    result = TinyLiveCanary(config, store, fake, now_fn=lambda: now, live_interlock=False).run_once(live_requested=True)
    assert result["status"] == "VALIDATED_ONLY"
    assert fake.validate_calls == 1
    assert fake.add_calls == 0
    assert store.conn.execute("SELECT COUNT(*) FROM phase6_canary_orders").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_phase6_one_entry_then_reconcile_position_and_target_exit(tmp_path: Path):
    clock = [1_900_000_000.0]
    config = cfg()
    store = ReadyStore(str(tmp_path / "roundtrip.db"), clock[0])
    approve(store, config, clock[0] - 1)
    seed(store, clock[0], price=100.0)
    fake = FakeKraken()
    canary = TinyLiveCanary(config, store, fake, now_fn=lambda: clock[0], live_interlock=True)

    first = canary.run_once(live_requested=True)
    assert first["status"] == "ORDER_PENDING"
    assert fake.add_calls == 1
    assert fake.deadman_calls == 1
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0

    clock[0] += 1
    seed(store, clock[0], price=105.0, run_id="obs-target")
    second = canary.run_once(live_requested=True)
    assert second["status"] == "EXIT_PENDING"
    assert fake.add_calls == 2

    clock[0] += 1
    third = canary.run_once(live_requested=True)
    assert third["status"] in {"DISARMED", "ARMED_WAITING"}
    position = CanaryStore(store).get_positions(limit=1)[0]
    assert position["status"] == "CLOSED"
    assert CanaryStore(store).scorecard()["completed_round_trips"] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_phase6_ambiguous_submit_halts_and_never_retries(tmp_path: Path):
    now = 1_900_000_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "unknown.db"), now)
    approve(store, config, now - 1)
    seed(store, now)
    fake = FakeKraken()
    fake.raise_on_add = True
    canary = TinyLiveCanary(config, store, fake, now_fn=lambda: now, live_interlock=True)
    first = canary.run_once(live_requested=True)
    assert first["status"] == "HALTED"
    assert fake.add_calls == 1
    assert CanaryStore(store).get_orders(limit=1)[0]["status"] == "UNKNOWN"
    second = canary.run_once(live_requested=True)
    assert second["status"] == "HALTED"
    assert fake.add_calls == 1


def test_phase6_rejects_nonisolated_account(tmp_path: Path):
    now = 1_900_000_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "external.db"), now)
    approve(store, config, now - 1)
    seed(store, now)
    fake = FakeKraken()
    fake.external_open = True
    result = TinyLiveCanary(config, store, fake, now_fn=lambda: now, live_interlock=True).run_once(live_requested=True)
    assert result["status"] == "HALTED"
    assert fake.add_calls == 0
    assert CanaryStore(store).open_incidents()[0]["category"] == "RECONCILIATION_FAILED"


def test_phase6_manual_halt_persists_across_clean_reconciliation(tmp_path: Path):
    now = 1_900_100_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "manual-halt.db"), now)
    approve(store, config, now - 1)
    seed(store, now, run_id="obs-manual-halt")
    phase6 = CanaryStore(store)
    phase6.set_state("HALTED", "manual_operator_halt")
    fake = FakeKraken()
    result = TinyLiveCanary(config, store, fake, now_fn=lambda: now, live_interlock=True).run_once(live_requested=True)
    assert result["status"] == "HALTED"
    assert "persistent_operator_or_safety_halt" in result["reasons"]
    assert fake.validate_calls == 0
    assert fake.add_calls == 0
    assert phase6.get_state()["state"] == "HALTED"


def test_phase6_daily_loss_limit_blocks_next_entry(tmp_path: Path):
    now = 1_900_200_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "daily-loss.db"), now)
    phase6 = CanaryStore(store)
    phase6.persist_position({
        "position_id": "closed-loss",
        "entry_client_order_id": "hv6-loss-entry",
        "symbol": "ETH/USD",
        "quantity": 0.01,
        "entry_price": 100.0,
        "entry_cost_quote": 1.0,
        "opened_ts": now - 60,
        "stop_price": 97.5,
        "target_price": 104.0,
        "horizon_ts": now - 30,
        "status": "CLOSED",
        "exit_client_order_id": "hv6-loss-exit",
        "exit_price": 80.0,
        "closed_ts": now - 1,
        "realized_pnl_quote": -1.50,
    })
    approve(store, config, now - 1)
    seed(store, now, run_id="obs-daily-loss")
    fake = FakeKraken()
    result = TinyLiveCanary(config, store, fake, now_fn=lambda: now, live_interlock=True).run_once(live_requested=True)
    assert result["status"] == "HALTED"
    assert "daily_loss_limit_breached" in result["reasons"]
    assert fake.validate_calls == 0
    assert fake.add_calls == 0
    assert phase6.get_state()["state"] == "HALTED"


def test_phase6_api_permissions_must_be_explicitly_visible(tmp_path: Path):
    now = 1_900_300_000.0
    config = cfg()
    store = ReadyStore(str(tmp_path / "permissions.db"), now)
    approve(store, config, now - 1)
    seed(store, now, run_id="obs-permissions")
    fake = FakeKraken()
    fake.api_key_info = lambda: {}
    result = TinyLiveCanary(config, store, fake, now_fn=lambda: now, live_interlock=True).run_once(live_requested=True)
    assert result["status"] == "HALTED"
    assert fake.validate_calls == 0
    assert fake.add_calls == 0
    assert CanaryStore(store).get_state()["state"] == "HALTED"
