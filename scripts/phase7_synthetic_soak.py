#!/usr/bin/env python3
"""Deterministic Phase-7 growth-governor control campaign.

No network client or credential loader is imported. The campaign creates four
fresh evidence blocks, walks the stage ladder one level at a time, verifies
human-only promotion, then injects an UNKNOWN order and confirms automatic
demotion. Synthetic returns are engineering controls, not profitability proof.
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
from strategies.volatility_breakout.canary_store import CanaryStore
from strategies.volatility_breakout.growth_lab import (
    PHASE7_ACKNOWLEDGEMENT,
    activate_approved_stage,
    build_growth_approval,
    build_growth_proposal,
    evaluate_demotion,
    growth_snapshot,
)
from strategies.volatility_breakout.growth_store import GrowthStore


def config() -> SimpleNamespace:
    return SimpleNamespace(
        phase7_growth_enabled=True,
        phase7_stage_activation_enabled=True,
        phase7_max_stage=4,
        phase7_allowed_symbols=["ETH/USD", "BTC/USD", "SOL/USD"],
        phase7_stage_notional_caps_usd=[5.0, 7.5, 10.0, 15.0, 20.0],
        phase7_stage_symbol_caps=[1, 1, 2, 2, 3],
        phase7_proposal_cooldown_sec=0,
        phase7_proposal_expiry_sec=604800,
        phase7_approval_lease_sec=3600,
        phase7_min_new_round_trips=50,
        phase7_min_distinct_days=14,
        phase7_require_positive_total_pnl=True,
        phase7_min_profit_factor=1.05,
        phase7_max_drawdown_bps=500.0,
        phase7_max_loss_rate=0.65,
        phase7_max_rejection_rate=0.05,
        phase7_max_mean_abs_slippage_bps=40.0,
        phase7_auto_demotion_enabled=True,
        phase6_max_notional_usd=20.0,
        phase6_allowed_symbols=["ETH/USD", "BTC/USD", "SOL/USD"],
        phase6_max_open_orders=1,
        phase6_max_open_positions=1,
        phase6_daily_loss_halt_usd=1.0,
    )


def seed_block(canary: CanaryStore, *, stage: int, base_ts: float, count: int = 56) -> None:
    for i in range(count):
        closed_ts = base_ts + (i % 14) * 86400 + (i // 14) * 60
        idx = stage * 10_000 + i
        pnl = 0.05 if i % 4 else -0.02
        entry_cost = 5.0 + stage
        entry_id = f"hv6-p7-entry-{idx}"
        exit_id = f"hv6-p7-exit-{idx}"
        for order_id, side, price, ts in (
            (entry_id, "buy", 100.0, closed_ts - 2),
            (exit_id, "sell", 101.0, closed_ts - 1),
        ):
            canary.persist_order({
                "client_order_id": order_id,
                "canary_intent_id": f"intent-{order_id}",
                "exchange_order_id": f"exchange-{order_id}",
                "symbol": "ETH/USD",
                "side": side,
                "status": "CLOSED",
                "quantity": entry_cost / 100.0,
                "limit_price": price,
                "filled_quantity": entry_cost / 100.0,
                "average_fill_price": price,
                "cost_quote": entry_cost,
                "fee_quote": 0.001,
                "created_ts": ts,
                "updated_ts": ts + 1,
                "live_submitted": True,
                "reconciled": True,
            })
        canary.persist_position({
            "position_id": f"phase7-position-{idx}",
            "entry_client_order_id": entry_id,
            "symbol": "ETH/USD",
            "quantity": entry_cost / 100.0,
            "entry_price": 100.0,
            "entry_cost_quote": entry_cost,
            "opened_ts": closed_ts - 60,
            "stop_price": 97.5,
            "target_price": 104.0,
            "horizon_ts": closed_ts,
            "status": "CLOSED",
            "exit_client_order_id": exit_id,
            "exit_price": 101.0,
            "closed_ts": closed_ts,
            "realized_pnl_quote": pnl,
        })


def run_campaign() -> dict[str, Any]:
    cfg = config()
    with tempfile.TemporaryDirectory(prefix="hivenance-phase7-soak-") as tmp:
        store = DataStoreAgent(str(Path(tmp) / "phase7.db"))
        canary = CanaryStore(store)
        growth = GrowthStore(store)
        clock = 1_900_000_000.0
        activations = []
        for target_stage in range(1, 5):
            seed_block(canary, stage=target_stage, base_ts=clock + 1)
            proposal_ts = clock + 15 * 86400
            proposal = build_growth_proposal(canary, growth, cfg, proposed_by=f"Synthetic Proposer {target_stage}", now_ts=proposal_ts)
            growth.persist_proposal(proposal.to_dict())
            approval = build_growth_approval(
                growth,
                cfg,
                approved_by=f"Synthetic Reviewer {target_stage}",
                acknowledgement=PHASE7_ACKNOWLEDGEMENT,
                now_ts=proposal_ts + 1,
            )
            growth.persist_approval(approval.to_dict())
            growth.mark_proposal_approved(approval.proposal_id, approval.approved_ts)
            result = activate_approved_stage(
                canary,
                growth,
                cfg,
                actor=f"Synthetic Activator {target_stage}",
                now_ts=proposal_ts + 2,
                env_interlock=True,
            )
            if result["stage"]["stage_id"] != target_stage:
                raise RuntimeError("growth ladder skipped or activated the wrong stage")
            activations.append(result["stage"])
            clock = proposal_ts + 3

        before_demotion = growth_snapshot(canary, growth, cfg)
        canary.persist_order({
            "client_order_id": "hv6-phase7-unknown",
            "canary_intent_id": "phase7-unknown-intent",
            "exchange_order_id": None,
            "symbol": "ETH/USD",
            "side": "buy",
            "status": "UNKNOWN",
            "quantity": 0.01,
            "limit_price": 100.0,
            "filled_quantity": 0.0,
            "created_ts": clock + 1,
            "updated_ts": clock + 1,
            "live_submitted": True,
            "reconciled": False,
        })
        demotion = evaluate_demotion(canary, growth, cfg, now_ts=clock + 2)
        after_demotion = growth_snapshot(canary, growth, cfg)
        legacy_orders = store.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        legacy_fills = store.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
        return {
            "kind": "deterministic_controlled_growth_governor_control",
            "market_profitability_evidence": False,
            "network_calls": 0,
            "credentials_loaded": False,
            "automatic_promotion": False,
            "human_activations": len(activations),
            "activated_stages": activations,
            "stage_before_sabotage": before_demotion["current_stage"],
            "demotion": demotion,
            "stage_after_sabotage": after_demotion["current_stage"],
            "open_growth_incidents": len(after_demotion["incidents"]),
            "legacy_order_rows": legacy_orders,
            "legacy_fill_rows": legacy_fills,
            "proposals": len(after_demotion["proposals"]),
            "approvals": len(after_demotion["approvals"]),
            "windows": len(after_demotion["windows"]),
            "audit_rows": len(after_demotion["audit"]),
            "passed": (
                len(activations) == 4
                and [x["stage_id"] for x in activations] == [1, 2, 3, 4]
                and demotion.get("demoted") is True
                and demotion.get("to_stage") == 3
                and legacy_orders == 0
                and legacy_fills == 0
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_campaign()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
