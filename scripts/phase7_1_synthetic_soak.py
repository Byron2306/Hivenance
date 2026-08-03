#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.config_agent import ConfigAgent
from agents.evidence_registry import EvidenceRegistryAgent
from agents.event_spine import EventSpineAgent
from agents.execution_parity import ExecutionParityAgent
from agents.ml_research_lab import MLResearchLabAgent
from agents.phoenix_authority import PhoenixAuthorityGuard, PROTECTED_ACTIONS
from agents.signal_marketplace import SignalMarketplaceAgent

REPORT = ROOT / "PHASE7_1_SYNTHETIC_AUTHORITY_REPORT.json"


def cfg(card_dir: str) -> SimpleNamespace:
    return SimpleNamespace(
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
        ml_model_card_dir=card_dir,
        ml_model_families_enabled=["freqai"],
        ml_research_max_pbo=0.20,
        ml_research_min_oos_trades=100,
        symbol="ETH/USD",
    )


def main() -> int:
    report: dict = {
        "phase": "7.1",
        "name": "integration_authority_reconciliation",
        "synthetic_only": True,
        "profitability_claim": False,
    }

    guard = PhoenixAuthorityGuard()
    denied = 0
    allowed = 0
    for _ in range(100):
        for component in guard.snapshot()["components"]:
            for action in PROTECTED_ACTIONS:
                decision = guard.decision(component, action)
                denied += int(not decision.allowed)
                allowed += int(decision.allowed)
    report["authority_requests"] = {
        "protected_requests": denied + allowed,
        "denied": denied,
        "unexpectedly_allowed": allowed,
    }

    with tempfile.TemporaryDirectory(prefix="hivenance-phase71-") as td:
        temp = Path(td)
        settings = temp / "settings.yaml"
        settings.write_text(
            "phase0_quarantine: true\ndry_run: true\nlive_mode: false\nhummingbot_v2_leverage: 1\n",
            encoding="utf-8",
        )
        config_agent = ConfigAgent(str(settings), str(temp / "snapshots"), str(temp / "audit.jsonl"))
        config_rejections = 0
        for _ in range(250):
            result = config_agent.update(
                {
                    "confirm_live": "ARM LIVE",
                    "dry_run": False,
                    "live_mode": True,
                    "onchain_enabled": True,
                    "public_bot_metrics_auto_promote": True,
                    "hummingbot_sidecar_live_enabled": True,
                    "market_making_quote_placement_enabled": True,
                    "hummingbot_v2_leverage": 5,
                },
                actor="synthetic_soak",
            )
            config_rejections += int(not result["ok"])
        report["config_guard"] = {
            "unsafe_update_attempts": 250,
            "rejected": config_rejections,
            "final_config": config_agent.read(),
        }

        c = cfg(str(temp / "cards"))
        evidence_registry = EvidenceRegistryAgent(c)
        evidence = []
        for i in range(100):
            evidence.append(
                evidence_registry.normalize(
                    source="freqtrade",
                    engine="freqtrade",
                    run_id=f"run-{i}",
                    symbol="ETH/USD",
                    strategy="external-test",
                    metrics={
                        "trades": 500,
                        "win_rate": 0.65,
                        "net_profit_pct": 8.0,
                        "max_drawdown_pct": 2.0,
                        "fee_pct": 0.1,
                        "slippage_pct": 0.1,
                        "walk_forward": True,
                    },
                    raw={"walk_forward": True},
                )
            )
        report["external_evidence"] = {
            "records": len(evidence),
            "unvalidated_imports": sum(1 for row in evidence if row.get("phoenix_status") == "UNVALIDATED_IMPORT"),
            "live_allowed": sum(1 for row in evidence if row.get("live_allowed")),
            "promotion_authority": sum(1 for row in evidence if row.get("promotion_authority") != "none"),
        }

        lab = MLResearchLabAgent(c)
        ml_candidates = []
        for i in range(25):
            ml_candidates.append(
                lab.propose(
                    "freqai",
                    symbol="ETH/USD",
                    metrics={
                        "layer3_evidence_id": f"external-{i}",
                        "layer3_evidence_verified": True,
                        "walk_forward_passed": True,
                        "pbo": 0.1,
                        "leakage_detected": False,
                        "oos_trades": 200,
                        "max_drawdown_pct": 2.0,
                        "negative_case_replay_passed": True,
                    },
                    persist=False,
                )
            )
        report["ml_candidates"] = {
            "records": len(ml_candidates),
            "phase2_ready": sum(1 for row in ml_candidates if row.get("verdict") == "phoenix_phase2_candidate_ready"),
            "live_allowed": sum(1 for row in ml_candidates if row.get("live_allowed")),
            "execution_authority": sum(1 for row in ml_candidates if row.get("execution_authority") != "none"),
        }

        parity_agent = ExecutionParityAgent(c)
        parity = []
        for i in range(100):
            parity.append(
                parity_agent.from_replay(
                    {
                        "run_id": f"replay-{i}",
                        "symbol": "ETH/USD",
                        "trades": 100,
                        "failed_exits": 0,
                        "slippage_pct": 0.001,
                        "fee_pct": 0.001,
                        "latency_ms": 10,
                    }
                )
            )
        report["execution_parity"] = {
            "diagnostics": len(parity),
            "live_allowed": sum(1 for row in parity if row.get("live_allowed")),
            "promotion_authority": sum(1 for row in parity if row.get("promotion_authority") != "none"),
        }

        market_agent = SignalMarketplaceAgent(c)
        rounds = []
        for i in range(100):
            rounds.append(
                market_agent.score_round(
                    [{"worker": f"worker-{i}", "action": "BUY", "confidence": 0.8}],
                    perf_by_worker={f"worker-{i}": {"total": 30, "wins": 20, "losses": 10}},
                    symbol="ETH/USD",
                )
            )
        report["signal_marketplace"] = {
            "rounds": len(rounds),
            "live_allowed": sum(1 for row in rounds if row.get("live_allowed")),
            "promotion_authority": sum(1 for row in rounds if row.get("promotion_authority") != "none"),
            "scaling_authority": sum(1 for row in rounds if row.get("scaling_authority") != "none"),
        }

        spine = EventSpineAgent()
        event, _ = spine.normalize(
            "buzz.canary.fill",
            {
                "payload": {
                    "observation_id": "obs-1",
                    "forecast_id": "forecast-1",
                    "simulation_id": "sim-1",
                    "validation_run_id": "validation-1",
                    "shadow_intent_id": "shadow-1",
                    "canary_intent_id": "canary-1",
                    "client_order_id": "hv6-1",
                    "fill_id": "fill-1",
                }
            },
        )
        report["event_spine"] = {
            "validated_count": spine.status()["validated_count"],
            "correlation_id": (event.get("buzz") or {}).get("correlation_id"),
        }

    violations = []
    if report["authority_requests"]["unexpectedly_allowed"]:
        violations.append("protected_authority_request_allowed")
    if report["config_guard"]["rejected"] != 250:
        violations.append("unsafe_config_update_not_rejected")
    for section in ("external_evidence", "ml_candidates", "execution_parity", "signal_marketplace"):
        for key in ("live_allowed", "promotion_authority", "scaling_authority", "execution_authority"):
            if report.get(section, {}).get(key, 0):
                violations.append(f"{section}:{key}")
    report["violations"] = violations
    report["pass"] = not violations
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
