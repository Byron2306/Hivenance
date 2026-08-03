from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.canary_store import CanaryStore
from strategies.volatility_breakout.growth_lab import (
    PHASE7_ACKNOWLEDGEMENT,
    PHASE7_RECOVERY_ACKNOWLEDGEMENT,
    activate_approved_stage,
    build_growth_approval,
    build_growth_proposal,
    evaluate_demotion,
    readiness_for_next_stage,
    resume_demoted_stage,
    stage_capped_config,
)
from strategies.volatility_breakout.growth_store import GrowthStore


def cfg(**overrides):
    values = dict(
        phase7_growth_enabled=True,
        phase7_stage_activation_enabled=False,
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
    values.update(overrides)
    return SimpleNamespace(**values)


def seed_live_evidence(store: DataStoreAgent, *, count: int = 56, base_ts: float = 1_900_000_000.0, start_index: int = 0):
    canary = CanaryStore(store)
    for i in range(count):
        idx = start_index + i
        closed_ts = base_ts + (i % 14) * 86400 + (i // 14) * 60
        pnl = 0.05 if i % 4 else -0.02
        entry_cost = 5.0
        entry_id = f"hv6-entry-{idx}"
        exit_id = f"hv6-exit-{idx}"
        canary.persist_order({
            "client_order_id": entry_id,
            "canary_intent_id": f"intent-{idx}",
            "exchange_order_id": f"exchange-entry-{idx}",
            "symbol": "ETH/USD",
            "side": "buy",
            "status": "CLOSED",
            "quantity": 0.05,
            "limit_price": 100.0,
            "filled_quantity": 0.05,
            "average_fill_price": 100.0,
            "cost_quote": entry_cost,
            "fee_quote": 0.001,
            "created_ts": closed_ts - 2,
            "updated_ts": closed_ts - 1,
            "live_submitted": True,
            "reconciled": True,
        })
        canary.persist_order({
            "client_order_id": exit_id,
            "canary_intent_id": f"exit-intent-{idx}",
            "exchange_order_id": f"exchange-exit-{idx}",
            "symbol": "ETH/USD",
            "side": "sell",
            "status": "CLOSED",
            "quantity": 0.05,
            "limit_price": 101.0,
            "filled_quantity": 0.05,
            "average_fill_price": 101.0,
            "cost_quote": entry_cost + pnl,
            "fee_quote": 0.001,
            "created_ts": closed_ts - 1,
            "updated_ts": closed_ts,
            "live_submitted": True,
            "reconciled": True,
        })
        canary.persist_position({
            "position_id": f"position-{idx}",
            "entry_client_order_id": entry_id,
            "symbol": "ETH/USD",
            "quantity": 0.05,
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


def test_phase7_gate_is_closed_without_genuine_canary_evidence(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "empty.db"))
    readiness = readiness_for_next_stage(CanaryStore(store), GrowthStore(store), cfg())
    assert readiness["ready_for_next_stage_proposal"] is False
    assert "insufficient_new_reconciled_round_trips" in readiness["reasons"]
    assert "non_positive_realized_pnl" in readiness["reasons"]
    with pytest.raises(ValueError):
        build_growth_proposal(CanaryStore(store), GrowthStore(store), cfg(), proposed_by="Byron")


def test_phase7_proposal_approval_activation_is_human_gated(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "growth.db"))
    seed_live_evidence(store)
    canary = CanaryStore(store)
    growth = GrowthStore(store)
    config = cfg(phase7_stage_activation_enabled=True)
    readiness = readiness_for_next_stage(canary, growth, config)
    assert readiness["ready_for_next_stage_proposal"] is True
    assert readiness["next_stage"] == 1

    proposal = build_growth_proposal(canary, growth, config, proposed_by="Byron", now_ts=1_902_000_000.0)
    assert proposal.to_stage == 1
    assert growth.persist_proposal(proposal.to_dict()) is True
    approval = build_growth_approval(
        growth,
        config,
        approved_by="Byron",
        acknowledgement=PHASE7_ACKNOWLEDGEMENT,
        now_ts=1_902_000_001.0,
    )
    growth.persist_approval(approval.to_dict())
    growth.mark_proposal_approved(approval.proposal_id, approval.approved_ts)

    with pytest.raises(ValueError):
        activate_approved_stage(canary, growth, config, actor="Byron", now_ts=1_902_000_002.0, env_interlock=False)

    result = activate_approved_stage(canary, growth, config, actor="Byron", now_ts=1_902_000_002.0, env_interlock=True)
    assert result["activated"] is True
    assert result["stage"]["name"] == "EMBER"
    assert result["stage"]["max_notional_usd"] == 7.5
    assert result["automatic_promotion"] is False
    assert growth.get_state()["current_stage"] == 1

    # A newly activated stage must earn a fresh evidence block.
    after = readiness_for_next_stage(canary, growth, config)
    assert after["ready_for_next_stage_proposal"] is False
    assert "insufficient_new_reconciled_round_trips" in after["reasons"]


def test_phase7_cooling_off_and_config_drift_are_enforced(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "cooldown.db"))
    seed_live_evidence(store)
    canary = CanaryStore(store)
    growth = GrowthStore(store)
    config = cfg(phase7_proposal_cooldown_sec=86400)
    proposal = build_growth_proposal(canary, growth, config, proposed_by="Byron", now_ts=1_902_000_000.0)
    growth.persist_proposal(proposal.to_dict())
    with pytest.raises(ValueError, match="cooling-off"):
        build_growth_approval(growth, config, approved_by="Byron", acknowledgement=PHASE7_ACKNOWLEDGEMENT, now_ts=1_902_000_001.0)

    drifted = cfg(phase7_proposal_cooldown_sec=86400, phase7_max_drawdown_bps=450.0)
    with pytest.raises(ValueError, match="drifted"):
        build_growth_approval(growth, drifted, approved_by="Byron", acknowledgement=PHASE7_ACKNOWLEDGEMENT, now_ts=1_902_100_000.0)


def test_phase7_stage_envelope_caps_phase6_authority(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "cap.db"))
    growth = GrowthStore(store)
    config = cfg(phase7_stage_activation_enabled=True, phase6_max_notional_usd=999.0)
    growth.set_state("ACTIVE", "test", current_stage=2, stage_started_ts=1.0, stage_start_round_trips=0)
    derived = stage_capped_config(config, growth)
    assert derived.phase6_max_notional_usd == 10.0
    assert derived.phase6_allowed_symbols == ["ETH/USD", "BTC/USD"]
    assert derived.phase6_max_open_positions == 1


def test_phase7_unknown_order_forces_automatic_demotion(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "demote.db"))
    seed_live_evidence(store)
    canary = CanaryStore(store)
    growth = GrowthStore(store)
    config = cfg(phase7_stage_activation_enabled=True)
    growth.set_state("ACTIVE", "test", current_stage=2, stage_started_ts=1_899_000_000.0, stage_start_round_trips=0)
    canary.persist_order({
        "client_order_id": "hv6-unknown",
        "canary_intent_id": "unknown-intent",
        "exchange_order_id": None,
        "symbol": "ETH/USD",
        "side": "buy",
        "status": "UNKNOWN",
        "quantity": 0.01,
        "limit_price": 100.0,
        "filled_quantity": 0.0,
        "created_ts": 1_903_000_000.0,
        "updated_ts": 1_903_000_000.0,
        "live_submitted": True,
        "reconciled": False,
    })
    result = evaluate_demotion(canary, growth, config, now_ts=1_903_000_001.0)
    assert result["demoted"] is True
    assert result["from_stage"] == 2
    assert result["to_stage"] == 1
    assert "unknown_order_state" in result["triggers"]
    assert growth.get_state()["state"] == "DEMOTED"
    assert growth.open_incidents()[0]["category"] == "AUTOMATIC_DEMOTION"


def test_phase7_never_skips_a_stage(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "skip.db"))
    seed_live_evidence(store)
    canary = CanaryStore(store)
    growth = GrowthStore(store)
    config = cfg()
    proposal = build_growth_proposal(canary, growth, config, proposed_by="Byron")
    assert proposal.from_stage == 0
    assert proposal.to_stage == 1


def test_phase7_stale_proposal_is_voided_by_new_unknown_order(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "stale.db"))
    seed_live_evidence(store)
    canary = CanaryStore(store)
    growth = GrowthStore(store)
    config = cfg()
    proposal = build_growth_proposal(canary, growth, config, proposed_by="Byron", now_ts=1_902_000_000.0)
    growth.persist_proposal(proposal.to_dict())
    canary.persist_order({
        "client_order_id": "hv6-stale-unknown",
        "canary_intent_id": "stale-intent",
        "exchange_order_id": None,
        "symbol": "ETH/USD",
        "side": "buy",
        "status": "UNKNOWN",
        "quantity": 0.01,
        "limit_price": 100.0,
        "filled_quantity": 0.0,
        "created_ts": 1_902_000_001.0,
        "updated_ts": 1_902_000_001.0,
        "live_submitted": True,
        "reconciled": False,
    })
    with pytest.raises(ValueError, match="safety recheck"):
        build_growth_approval(
            growth,
            config,
            approved_by="Byron",
            acknowledgement=PHASE7_ACKNOWLEDGEMENT,
            now_ts=1_902_000_002.0,
        )
    assert growth.latest_proposal()["status"] == "REJECTED"


def test_phase7_recovery_is_human_only_and_requires_clean_reconciliation(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "recover.db"))
    seed_live_evidence(store)
    canary = CanaryStore(store)
    growth = GrowthStore(store)
    config = cfg(phase7_stage_activation_enabled=True)
    growth.set_state("ACTIVE", "test", current_stage=2, stage_started_ts=1_899_000_000.0, stage_start_round_trips=0)
    canary.persist_order({
        "client_order_id": "hv6-recovery-unknown",
        "canary_intent_id": "recovery-intent",
        "exchange_order_id": None,
        "symbol": "ETH/USD",
        "side": "buy",
        "status": "UNKNOWN",
        "quantity": 0.01,
        "limit_price": 100.0,
        "filled_quantity": 0.0,
        "created_ts": 1_903_000_000.0,
        "updated_ts": 1_903_000_000.0,
        "live_submitted": True,
        "reconciled": False,
    })
    demotion = evaluate_demotion(canary, growth, config, now_ts=1_903_000_001.0)
    assert demotion["to_stage"] == 1
    with pytest.raises(ValueError):
        resume_demoted_stage(
            canary, growth, config, actor="Byron",
            acknowledgement=PHASE7_RECOVERY_ACKNOWLEDGEMENT,
            now_ts=1_903_000_002.0, env_interlock=True,
        )
    incident_id = growth.open_incidents()[0]["incident_id"]
    assert growth.resolve_incident(incident_id, "exchange query confirmed no live order", now_ts=1_903_000_003.0)
    with store._lock:
        store.conn.execute(
            "UPDATE phase6_canary_orders SET status='CANCELED', reconciled=1, updated_ts=? WHERE client_order_id=?",
            (1_903_000_004.0, "hv6-recovery-unknown"),
        )
        store.conn.commit()
    canary.persist_reconciliation({
        "reconciliation_id": "clean-after-incident",
        "ts": 1_903_000_005.0,
        "status": "CLEAN",
        "open_orders_count": 0,
        "canary_open_orders_count": 0,
        "unknown_orders_count": 0,
        "active_positions_count": 0,
        "balance_snapshot": {},
    })
    result = resume_demoted_stage(
        canary, growth, config, actor="Byron",
        acknowledgement=PHASE7_RECOVERY_ACKNOWLEDGEMENT,
        now_ts=1_903_000_006.0, env_interlock=True,
    )
    assert result["recovered"] is True
    assert result["automatic_recovery"] is False
    assert result["stage"]["stage_id"] == 1
    assert growth.get_state()["state"] == "ACTIVE"
