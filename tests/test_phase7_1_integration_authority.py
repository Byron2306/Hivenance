from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from agents.config_agent import ConfigAgent
from agents.evidence_registry import EvidenceRegistryAgent
from agents.execution_parity import ExecutionParityAgent
from agents.ml_research_lab import MLResearchLabAgent
from agents.phoenix_authority import PhoenixAuthorityGuard, PROTECTED_ACTIONS
from agents.signal_marketplace import SignalMarketplaceAgent


ROOT = Path(__file__).resolve().parents[1]


def base_cfg(**updates):
    values = dict(
        promotion_min_paper_trades=25,
        promotion_min_win_rate=0.52,
        promotion_max_drawdown_pct=5.0,
        execution_parity_max_latency_ms=1500,
        execution_parity_max_slippage_pct=0.01,
        execution_parity_min_fill_ratio=0.98,
        execution_parity_max_queue_position_risk=0.35,
        signal_marketplace_min_originality=0.35,
        signal_marketplace_max_drawdown=0.45,
        signal_marketplace_min_stability=0.2,
        signal_marketplace_min_realized_samples=25,
        signal_marketplace_reward_scale=100.0,
        signal_marketplace_weight_strength=0.2,
        signal_marketplace_weight_realized_outcome=0.3,
        signal_marketplace_weight_originality=0.2,
        signal_marketplace_weight_stability=0.15,
        signal_marketplace_weight_win_rate=0.15,
        signal_marketplace_weight_drawdown_penalty=0.35,
        ml_model_card_dir="data/model_cards",
        ml_model_families_enabled=["freqai"],
        ml_research_max_pbo=0.20,
        ml_research_min_oos_trades=100,
    )
    values.update(updates)
    return SimpleNamespace(**values)


def test_all_legacy_protected_actions_are_denied():
    guard = PhoenixAuthorityGuard()
    for component in guard.snapshot()["components"]:
        for action in PROTECTED_ACTIONS:
            decision = guard.decision(component, action)
            assert decision.allowed is False
            assert decision.reason == "phoenix_authority_locked"


def test_config_agent_retires_arm_live_and_blocks_unsafe_rollback(tmp_path: Path):
    config_path = tmp_path / "settings.yaml"
    config_path.write_text(yaml.safe_dump({
        "phase0_quarantine": True,
        "dry_run": True,
        "live_mode": False,
        "hummingbot_v2_leverage": 1,
    }))
    agent = ConfigAgent(str(config_path), str(tmp_path / "snapshots"), str(tmp_path / "audit.jsonl"))
    rejected = agent.update({"confirm_live": "ARM LIVE", "live_mode": True}, actor="test")
    assert rejected["ok"] is False
    assert "legacy_arm_live_retired" in rejected["errors"]["confirm_live"]
    assert "phoenix_authority_locked" in rejected["errors"]["live_mode"]

    unsafe = tmp_path / "snapshots/settings-unsafe.yaml"
    unsafe.parent.mkdir(parents=True, exist_ok=True)
    unsafe.write_text(yaml.safe_dump({"dry_run": False, "live_mode": True, "hummingbot_v2_leverage": 5}))
    rollback = agent.rollback("unsafe", actor="test")
    assert rollback["ok"] is False
    assert rollback["error"] == "unsafe_snapshot_rejected"


def test_external_evidence_never_emits_live_readiness():
    registry = EvidenceRegistryAgent(base_cfg())
    record = registry.normalize(
        source="freqtrade",
        engine="freqtrade",
        run_id="r1",
        symbol="ETH/USD",
        strategy="test",
        metrics={
            "trades": 500,
            "win_rate": 0.70,
            "net_profit_pct": 10.0,
            "max_drawdown_pct": 2.0,
            "fee_pct": 0.1,
            "slippage_pct": 0.1,
            "walk_forward": True,
        },
        raw={"walk_forward": True},
    )
    assert record["verdict"] == "external_research_passed"
    assert record["phoenix_status"] == "UNVALIDATED_IMPORT"
    assert record["promotion_authority"] == "none"
    assert record["live_allowed"] is False
    assert record["next_required_phase"] == 2


def test_ml_execution_parity_and_marketplace_are_non_authoritative(tmp_path: Path):
    cfg = base_cfg(ml_model_card_dir=str(tmp_path / "cards"))
    ml = MLResearchLabAgent(cfg).validate({
        "layer3_evidence_id": "external-1",
        "layer3_evidence_verified": True,
        "walk_forward_passed": True,
        "pbo": 0.1,
        "leakage_detected": False,
        "oos_trades": 200,
        "max_drawdown_pct": 2.0,
        "negative_case_replay_passed": True,
    })
    assert ml["verdict"] == "phoenix_phase2_candidate_ready"

    parity = ExecutionParityAgent(cfg).from_replay({
        "run_id": "r1", "symbol": "ETH/USD", "trades": 100,
        "failed_exits": 0, "slippage_pct": 0.001,
        "fee_pct": 0.001, "latency_ms": 10,
    })
    assert parity["execution_authority"] == "none"
    assert parity["promotion_authority"] == "none"
    assert parity["live_allowed"] is False

    market = SignalMarketplaceAgent(cfg).score_round([
        {"worker": "A", "action": "BUY", "confidence": 0.8},
    ], perf_by_worker={"A": {"total": 30, "wins": 20, "losses": 10}})
    assert market["execution_authority"] == "none"
    assert market["promotion_authority"] == "none"
    assert market["scaling_authority"] == "none"
    assert market["live_allowed"] is False


def test_no_legacy_tiny_live_writes_remain():
    coordinator = (ROOT / "agents/coordinator.py").read_text()
    promoter = (ROOT / "scripts/promote_symbols.py").read_text()
    assert 'current["stage"] = "tiny_live"' not in coordinator
    assert '"stage": "tiny_live"' not in coordinator
    assert 'PUBLIC_BOT_AUTO_PROMOTED' not in coordinator
    assert 'STAGES = ("paper", "tiny_live", "normal")' not in promoter


def test_ordinary_main_and_desktop_are_research_only():
    source = (ROOT / "main.py").read_text()
    coordinator = (ROOT / "agents/coordinator.py").read_text()
    ui = (ROOT / "agents/ui_agent.py").read_text()
    assert "Legacy coordinator live execution is retired" in source
    assert "cfg.live_mode = True" not in source
    assert "confirm_live_required" not in coordinator
    assert "ARM LIVE" not in coordinator
    assert "Type ARM LIVE" not in ui
    assert "Legacy desktop resume is retired" in ui
    assert "Use the dedicated Phase-6 or Phase-7 operator process" in ui
