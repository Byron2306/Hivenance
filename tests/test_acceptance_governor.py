from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from strategies.volatility_breakout.acceptance_governor import (
    decide_next_action,
    load_phase6_soak_report,
    phase6_control_gate,
    real_evidence_gate,
)


@dataclass
class GovernorConfig:
    symbol: str = "ETH/USD"
    phase6_allowed_symbols: tuple[str, ...] = ("ETH/USD",)
    phase6_allowed_directions: tuple[str, ...] = ("UP",)
    phase6_live_submission_enabled: bool = False
    phase6_rapid_paper_canary_enabled: bool = False


ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "config/settings.yaml"


def _truth(**phase_decisions: str) -> dict:
    phases = {
        str(phase): {"decision": phase_decisions.get(str(phase), "REFUSE"), "reasons": [], "metrics": {}}
        for phase in range(1, 6)
    }
    return {"phases": phases, "safety": {"status": "CLEAN"}}


def _decide(truth: dict, **kwargs):
    return decide_next_action(
        truth=truth,
        cfg=GovernorConfig(),
        root=ROOT,
        settings=SETTINGS,
        exchange="kraken",
        **kwargs,
    )


def test_safety_alert_takes_priority_over_everything() -> None:
    truth = _truth(**{"1": "ALLOW", "2": "ALLOW"})
    truth["safety"] = {"status": "TRIPPED"}
    decision = _decide(truth)
    assert decision.current_blocker == "safety_alert"
    assert decision.next_action.action == "STOP_SAFETY_ALERT"
    assert decision.next_action.requires_human is True


def test_no_evidence_waits_for_new_observations() -> None:
    decision = _decide(_truth())
    assert decision.current_blocker == "waiting"
    assert decision.next_action.action == "WAIT_FOR_NEW_OBSERVATIONS"
    assert decision.next_action.safe_to_auto_execute is False


def test_phase1_allow_requests_phase2_settlement() -> None:
    decision = _decide(_truth(**{"1": "ALLOW"}))
    assert decision.current_blocker == "phase2_settlement_needed"
    assert decision.next_action.action == "RUN_PHASE2_SETTLE_ONLY"
    assert decision.next_action.safe_to_auto_execute is True
    assert "run_phase2_hypotheses.py" in " ".join(decision.next_action.command)


def test_phase2_allow_requests_phase3_replay() -> None:
    decision = _decide(_truth(**{"1": "ALLOW", "2": "ALLOW"}))
    assert decision.current_blocker == "phase3_replay_needed"
    assert decision.next_action.action == "RUN_PHASE3_REPLAY_ONLY"


def test_phase3_allow_requests_phase4_validation() -> None:
    decision = _decide(_truth(**{"1": "ALLOW", "2": "ALLOW", "3": "ALLOW"}))
    assert decision.current_blocker == "phase4_compatible_champion_needed"
    assert decision.next_action.action == "RUN_PHASE4_VALIDATION_ONLY"


def test_phase4_allow_with_compatible_champion_requests_freeze_approval() -> None:
    truth = _truth(**{"1": "ALLOW", "2": "ALLOW", "3": "ALLOW", "4": "ALLOW"})
    truth["phases"]["4"]["metrics"] = {
        "champion": {
            "candidate_key": "breakout_continuation_v1::marketable_limit",
            "model_id": "breakout_continuation_v1",
            "order_policy": "marketable_limit",
            "symbol": "ETH/USD",
            "direction": "UP",
        }
    }
    decision = _decide(truth)
    assert decision.current_blocker == "phase5_freeze_approval_required"
    assert decision.next_action.action == "REQUEST_PHASE5_FREEZE_APPROVAL"
    assert decision.next_action.requires_human is True


def test_active_incompatible_freeze_falls_back_to_phase4_validation() -> None:
    truth = _truth(**{"1": "ALLOW", "2": "ALLOW", "3": "ALLOW", "4": "ALLOW"})
    freeze = {
        "freeze_id": "freeze-1",
        "candidate_key": "breakout_continuation_v1::marketable_limit",
        "symbol": "BTC/USD",
        "direction": "DOWN",
    }
    decision = _decide(truth, active_freeze=freeze)
    assert decision.current_blocker == "active_phase5_freeze_not_phase6_compatible"
    assert decision.next_action.action == "RUN_PHASE4_VALIDATION_ONLY"
    assert decision.next_action.safe_to_auto_execute is True


def test_active_small_window_down_freeze_stays_shadow_research_not_phase4_rerun() -> None:
    truth = _truth(**{"1": "ALLOW", "2": "ALLOW", "3": "ALLOW", "4": "ALLOW"})
    freeze = {
        "freeze_id": "freeze-small-window-down",
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
    }
    decision = _decide(truth, active_freeze=freeze)
    assert decision.current_blocker == "small_window_shadow_only_not_phase6_spot_compatible"
    assert decision.next_action.action == "RUN_SMALL_WINDOW_TREND_TAPE"
    assert decision.next_action.safe_to_auto_execute is True
    assert "run_small_window_trend_tape.py" in " ".join(decision.next_action.command)


def test_active_compatible_freeze_with_phase5_not_allow_requests_shadow_only() -> None:
    truth = _truth(**{"1": "ALLOW", "2": "ALLOW", "3": "ALLOW", "4": "ALLOW"})
    freeze = {
        "freeze_id": "freeze-1",
        "candidate_key": "breakout_continuation_v1::marketable_limit",
        "symbol": "ETH/USD",
        "direction": "UP",
    }
    decision = _decide(truth, active_freeze=freeze)
    assert decision.current_blocker == "phase5_shadow_evidence_incomplete"
    assert decision.next_action.action == "RUN_PHASE5_SHADOW_ONLY"
    assert decision.next_action.safe_to_auto_execute is True


def test_phase5_allow_with_compatible_freeze_requests_canary_approval() -> None:
    truth = _truth(**{"1": "ALLOW", "2": "ALLOW", "3": "ALLOW", "4": "ALLOW", "5": "ALLOW"})
    freeze = {
        "freeze_id": "freeze-1",
        "candidate_key": "breakout_continuation_v1::marketable_limit",
        "symbol": "ETH/USD",
        "direction": "UP",
    }
    decision = _decide(truth, active_freeze=freeze)
    assert decision.current_blocker == "phase6_human_approval_required"
    assert decision.next_action.action == "REQUEST_PHASE6_CANARY_APPROVAL"
    assert decision.next_action.requires_human is True
    assert "--approve-canary" in decision.next_action.command


def test_phase5_allow_with_small_window_down_freeze_runs_rapid_paper_canary() -> None:
    cfg = GovernorConfig(
        phase6_allowed_symbols=("ONDO/USD",),
        phase6_allowed_directions=("UP", "DOWN"),
        phase6_rapid_paper_canary_enabled=True,
        phase6_live_submission_enabled=False,
    )
    truth = _truth(**{"1": "ALLOW", "2": "ALLOW", "3": "ALLOW", "4": "ALLOW", "5": "ALLOW"})
    freeze = {
        "freeze_id": "freeze-small-window-down",
        "candidate_key": "small_window_trend_comparison_v1|recent_delta_volatility|ONDO/USD|DOWN|1800|marketable_limit",
        "model_id": "small_window_trend_comparison_v1",
        "symbol": "ONDO/USD",
        "direction": "DOWN",
    }
    decision = decide_next_action(
        truth=truth,
        cfg=cfg,
        root=ROOT,
        settings=SETTINGS,
        exchange="kraken",
        active_freeze=freeze,
        profile=ROOT / "config/high_vol_low_stakes.yaml",
        database=ROOT / "data/swarm_data.db",
    )

    assert decision.current_blocker == "phase6_rapid_paper_canary_ready"
    assert decision.next_action.action == "RUN_PHASE6_RAPID_PAPER_CANARY"
    assert decision.next_action.safe_to_auto_execute is True
    assert decision.next_action.requires_human is False
    assert "run_phase6_canary.py" in " ".join(decision.next_action.command)


def test_real_evidence_gate_stops_at_first_non_allow_phase() -> None:
    assert real_evidence_gate(_truth(**{"1": "ALLOW", "2": "ALLOW"})) == "phase2"
    assert real_evidence_gate(_truth(**{"1": "ALLOW", "2": "ALLOW", "4": "ALLOW"})) == "phase2"
    assert real_evidence_gate(_truth()) == "none"


def test_phase6_control_gate_requires_exact_deterministic_shape() -> None:
    assert phase6_control_gate(None) == "unproven"
    assert phase6_control_gate({"campaign": {"kind": "something_else"}}) == "unproven"

    good_report = {
        "campaign": {
            "kind": "deterministic_fake_exchange_safety_control",
            "market_profitability_evidence": False,
            "network_calls": 0,
            "phase7_review_gate": {"ready_for_phase7_review": True},
            "legacy_orders_rows": 0,
            "legacy_fills_rows": 0,
            "unknown_orders": 0,
            "open_incidents": 0,
        },
        "ambiguity_sabotage": {
            "first_status": "HALTED",
            "second_status": "HALTED",
            "add_calls_after_two_cycles": 1,
        },
    }
    assert phase6_control_gate(good_report) == "phase6_control"


def test_load_phase6_soak_report_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_phase6_soak_report(tmp_path / "does_not_exist.json") == {}


def test_load_phase6_soak_report_reads_persisted_json(tmp_path: Path) -> None:
    path = tmp_path / "soak.json"
    path.write_text('{"campaign": {"kind": "deterministic_fake_exchange_safety_control"}}', encoding="utf-8")
    report = load_phase6_soak_report(path)
    assert report["campaign"]["kind"] == "deterministic_fake_exchange_safety_control"
