from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.canary_lab import (
    PHASE6_ACKNOWLEDGEMENT,
    TinyLiveCanary,
    build_canary_approval,
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
