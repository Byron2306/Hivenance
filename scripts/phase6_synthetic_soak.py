#!/usr/bin/env python3
"""Deterministic fake-exchange Phase-6 control campaign.

This script never opens a network socket and never loads exchange credentials.
It validates lifecycle, one-entry approvals, reconciliation, exits, no legacy
order mutation, readiness accounting, and ambiguous-submit halt semantics.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.canary_lab import (
    PHASE6_ACKNOWLEDGEMENT,
    TinyLiveCanary,
    build_canary_approval,
)
from strategies.volatility_breakout.canary_store import CanaryStore
from strategies.volatility_breakout.shadow_flight import frozen_config_hash


class SyntheticReadyStore(DataStoreAgent):
    def __init__(self, path: str, now: float) -> None:
        super().__init__(path)
        self.freeze = {
            "freeze_id": "synthetic-freeze-phase5",
            "phase4_run_id": "synthetic-phase4-run",
            "candidate_key": "breakout_continuation_v1::marketable_limit",
            "model_id": "breakout_continuation_v1",
            "order_policy": "marketable_limit",
            "approved_by": "Synthetic Control",
            "approved_ts": now - 3600,
            "phase4_dataset_hash": "synthetic-phase4-dataset",
            "config_hash": "",
            "status": "ACTIVE",
        }

    def get_phase5_active_freeze(self) -> dict[str, Any]:
        return dict(self.freeze)

    def get_phase5_readiness(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "phase": 5,
            "ready_for_phase6_review": True,
            "execution_eligible": False,
            "transmission_attempts": 0,
            "real_orders_submitted": 0,
            "reasons": [],
        }


class FakeKraken:
    """In-memory exchange double. No HTTP client exists in this process."""

    def __init__(self, *, ambiguous_first_add: bool = False) -> None:
        self.validate_calls = 0
        self.add_calls = 0
        self.deadman_calls = 0
        self.orders: dict[str, dict[str, Any]] = {}
        self.ambiguous_first_add = ambiguous_first_add

    def api_key_info(self) -> dict[str, Any]:
        return {"permissions": [
            "Orders and trades - Create & modify orders",
            "Orders and trades - Query open orders & trades",
        ]}

    def system_status(self) -> dict[str, str]:
        return {"status": "online"}

    def asset_pairs(self, _pair: str) -> dict[str, Any]:
        return {"XETHZUSD": {
            "altname": "ETHUSD", "pair_decimals": 2, "lot_decimals": 6,
            "ordermin": "0.001", "costmin": "1.0", "status": "online",
        }}

    def balances(self) -> dict[str, str]:
        return {"ZUSD": "100.0", "XETH": "0.0"}

    def open_orders(self) -> dict[str, Any]:
        return {"open": {}}

    def validate_order(self, _payload: dict[str, Any]) -> dict[str, Any]:
        self.validate_calls += 1
        return {"descr": {"order": "synthetically validated"}}

    def add_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.add_calls += 1
        if self.ambiguous_first_add and self.add_calls == 1:
            raise TimeoutError("synthetic ambiguous submission timeout")
        txid = f"SYNTH-TX-{self.add_calls:05d}"
        quantity = float(payload["volume"])
        price = float(payload["price"])
        self.orders[txid] = {
            "status": "closed", "vol": str(quantity), "vol_exec": str(quantity),
            "cost": str(quantity * price), "fee": "0.001",
            "price": str(price), "cl_ord_id": payload["cl_ord_id"],
        }
        return {"txid": [txid], "descr": {"order": "synthetically accepted"}}

    def query_orders(self, txids: list[str]) -> dict[str, Any]:
        return {txid: self.orders[txid] for txid in txids if txid in self.orders}

    def cancel_all_after(self, timeout_sec: int) -> dict[str, Any]:
        self.deadman_calls += 1
        return {"currentTime": "synthetic", "triggerTime": "synthetic", "timeout": timeout_sec}

    def cancel_all(self) -> dict[str, int]:
        return {"count": 0}


def config() -> SimpleNamespace:
    return SimpleNamespace(
        exchange="kraken", symbol="ETH/USD",
        phase6_canary_enabled=True, phase6_live_submission_enabled=True,
        phase6_allowed_symbols=["ETH/USD"], phase6_max_notional_usd=5.0,
        phase6_max_entry_orders_per_approval=1, phase6_approval_lease_sec=900,
        phase6_candidate_max_age_sec=30, phase6_market_data_max_age_sec=10,
        phase6_min_data_quality=0.99, phase6_max_spread_bps=30.0,
        phase6_max_slippage_bps=40.0, phase6_stop_distance_bps=250.0,
        phase6_target_distance_bps=400.0, phase6_deadman_timeout_sec=60,
        phase6_require_isolated_account=True, phase6_min_phase7_round_trips=50,
        phase5_readiness_min_distinct_days=30, phase5_readiness_min_settled=100,
        phase5_readiness_max_cost_mae_bps=20.0, phase5_readiness_min_fill_ratio=0.5,
        phase5_readiness_require_positive_mean=True,
        phase2_horizons_seconds=[300], phase2_min_data_quality=0.99,
        phase2_minimum_edge_multiple=2.0, phase2_breakout_min_expansion=1.5,
        phase2_breakout_min_volume_zscore=1.0, phase2_breakout_min_return_zscore=1.0,
        phase2_reversion_min_stretch_zscore=2.0, phase2_reversion_min_range_extreme=0.9,
        phase3_simulated_equity_usd=1000.0, phase3_risk_fraction=0.0005,
        phase3_sleeve_fraction=0.02, phase3_max_notional_usd=25.0,
        phase3_max_depth_participation=0.01, phase3_min_notional_usd=5.0,
        phase3_maker_fee_bps=10.0, phase3_taker_fee_bps=20.0,
        phase3_max_entry_spread_bps=60.0, phase5_shadow_reference_notional_usd=10.0,
        phase5_shadow_stop_distance_bps=250.0, phase5_shadow_max_intents_per_cycle=25,
        phase5_shadow_chase_timeout_sec=30, phase5_shadow_entry_latency_ms=250.0,
    )


def seed(store: SyntheticReadyStore, now: float, sequence: int, price: float) -> None:
    observation_id = f"phase6-observation-{sequence}"
    shadow_id = f"phase6-shadow-{sequence}"
    forecast_id = f"phase6-forecast-{sequence}"
    with store._lock:
        store.conn.execute(
            """INSERT OR REPLACE INTO observation_snapshots
            (run_id,ts,venue,symbol,price,quote_volume_24h,spread_bps,depth_usd_25bps,
             volatility_expansion,volume_zscore,book_imbalance,data_quality,
             observation_eligible,execution_eligible,rejection_reasons,payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (observation_id, now, "kraken", "ETH/USD", price, 100_000_000.0, 4.0, 500_000.0,
             1.8, 2.0, 0.2, 1.0, 1, 0, "[]",
             json.dumps({"price": price, "ts": now, "data_quality": 1.0, "spread_bps": 4.0})),
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
            (shadow_id, forecast_id, store.freeze["freeze_id"], store.freeze["phase4_run_id"],
             store.freeze["candidate_key"], store.freeze["model_id"], store.freeze["order_policy"],
             "kraken", "ETH/USD", "UP", "buy", "limit", "IOC", 0.05, 5.0, price,
             price * 1.001, 250.0, 0.5, 100.0, 20.0, 80.0, 0.7, 300, now, now + 300,
             1.0, 4.0, 500_000.0, "kraken-v1", "synthetic-shadow-config", "PENDING",
             "NEVER_TRANSMITTED", 0, 0, 0, 0, 0, 0, 0, "{}"),
        )
        store.conn.commit()


def seed_observation_only(store: SyntheticReadyStore, now: float, sequence: int, price: float) -> None:
    with store._lock:
        store.conn.execute(
            """INSERT OR REPLACE INTO observation_snapshots
            (run_id,ts,venue,symbol,price,quote_volume_24h,spread_bps,depth_usd_25bps,
             volatility_expansion,volume_zscore,book_imbalance,data_quality,
             observation_eligible,execution_eligible,rejection_reasons,payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"phase6-exit-observation-{sequence}", now, "kraken", "ETH/USD", price,
             100_000_000.0, 4.0, 500_000.0, 1.8, 2.0, 0.2, 1.0, 1, 0, "[]",
             json.dumps({"price": price, "ts": now, "data_quality": 1.0, "spread_bps": 4.0})),
        )
        store.conn.commit()


def approve(store: SyntheticReadyStore, cfg: SimpleNamespace, now: float, sequence: int) -> None:
    store.freeze["config_hash"] = frozen_config_hash(cfg)
    approval = build_canary_approval(
        store, cfg, approved_by=f"Synthetic Operator {sequence}",
        acknowledgement=PHASE6_ACKNOWLEDGEMENT, approved_ts=now,
    )
    CanaryStore(store).persist_approval(approval.to_dict())


def run_campaign(round_trips: int) -> dict[str, Any]:
    cfg = config()
    base = 1_900_000_000.0
    with tempfile.TemporaryDirectory(prefix="hivenance-phase6-soak-") as tmp:
        db = Path(tmp) / "soak.db"
        store = SyntheticReadyStore(str(db), base)
        fake = FakeKraken()
        clock = [base]
        canary = TinyLiveCanary(cfg, store, fake, now_fn=lambda: clock[0], live_interlock=True)
        statuses: dict[str, int] = {}
        for sequence in range(round_trips):
            entry_price = 100.0 + sequence * 0.01
            seed(store, clock[0], sequence, entry_price)
            approve(store, cfg, clock[0] - 1.0, sequence)
            first = canary.run_once(live_requested=True)
            statuses[first["status"]] = statuses.get(first["status"], 0) + 1
            if first["status"] != "ORDER_PENDING":
                raise RuntimeError(f"entry round {sequence} did not submit: {first}")
            clock[0] += 1.0
            seed_observation_only(store, clock[0], sequence, entry_price * 1.05)
            second = canary.run_once(live_requested=True)
            statuses[second["status"]] = statuses.get(second["status"], 0) + 1
            if second["status"] != "EXIT_PENDING":
                raise RuntimeError(f"exit round {sequence} did not submit: {second}")
            clock[0] += 1.0
            third = canary.run_once(live_requested=True)
            statuses[third["status"]] = statuses.get(third["status"], 0) + 1
            if CanaryStore(store).get_open_position():
                raise RuntimeError(f"position remained open after round {sequence}")
            clock[0] += 1.0

        phase6 = CanaryStore(store)
        scorecard = phase6.scorecard()
        readiness = phase6.readiness(min_round_trips=cfg.phase6_min_phase7_round_trips)
        legacy_orders = store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        legacy_fills = store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
        phase6_orders = store.conn.execute("SELECT COUNT(*) FROM phase6_canary_orders").fetchone()[0]
        approvals = store.conn.execute("SELECT COUNT(*) FROM phase6_canary_approvals").fetchone()[0]
        reconciliations = store.conn.execute("SELECT COUNT(*) FROM phase6_canary_reconciliations").fetchone()[0]
        report = {
            "kind": "deterministic_fake_exchange_safety_control",
            "market_profitability_evidence": False,
            "network_calls": 0,
            "credentials_loaded": False,
            "requested_round_trips": round_trips,
            "completed_round_trips": scorecard["completed_round_trips"],
            "phase6_orders": phase6_orders,
            "approvals": approvals,
            "reconciliations": reconciliations,
            "validate_only_calls": fake.validate_calls,
            "fake_add_calls": fake.add_calls,
            "deadman_refreshes": fake.deadman_calls,
            "legacy_orders_rows": legacy_orders,
            "legacy_fills_rows": legacy_fills,
            "open_incidents": scorecard["open_incidents"],
            "unknown_orders": scorecard["unknown_orders"],
            "open_positions": scorecard["open_positions"],
            "automatic_scaling": False,
            "leverage": 1,
            "phase7_review_gate": readiness,
            "status_counts": statuses,
        }
        if legacy_orders or legacy_fills:
            raise RuntimeError("Phase-6 synthetic campaign mutated legacy live tables")
        if report["completed_round_trips"] != round_trips:
            raise RuntimeError("round-trip accounting mismatch")
        if not readiness["ready_for_phase7_review"]:
            raise RuntimeError(f"expected synthetic Phase-7 review gate to open: {readiness}")
        return report


def run_ambiguity_sabotage() -> dict[str, Any]:
    cfg = config()
    now = 1_910_000_000.0
    with tempfile.TemporaryDirectory(prefix="hivenance-phase6-ambiguity-") as tmp:
        store = SyntheticReadyStore(str(Path(tmp) / "ambiguity.db"), now)
        seed(store, now, 999, 100.0)
        approve(store, cfg, now - 1.0, 999)
        fake = FakeKraken(ambiguous_first_add=True)
        canary = TinyLiveCanary(cfg, store, fake, now_fn=lambda: now, live_interlock=True)
        first = canary.run_once(live_requested=True)
        second = canary.run_once(live_requested=True)
        phase6 = CanaryStore(store)
        return {
            "first_status": first.get("status"),
            "second_status": second.get("status"),
            "add_calls_after_two_cycles": fake.add_calls,
            "state": phase6.get_state(),
            "unknown_orders": phase6.scorecard()["unknown_orders"],
            "open_incidents": phase6.scorecard()["open_incidents"],
            "legacy_orders_rows": store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
            "expected": "HALT on ambiguity; no retry; one add attempt",
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round-trips", type=int, default=60)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "campaign": run_campaign(max(1, args.round_trips)),
        "ambiguity_sabotage": run_ambiguity_sabotage(),
    }
    if report["ambiguity_sabotage"]["first_status"] != "HALTED":
        raise RuntimeError("ambiguity sabotage did not halt immediately")
    if report["ambiguity_sabotage"]["second_status"] != "HALTED":
        raise RuntimeError("ambiguity sabotage did not remain halted")
    if report["ambiguity_sabotage"]["add_calls_after_two_cycles"] != 1:
        raise RuntimeError("ambiguous submission was retried")
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
