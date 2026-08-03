from __future__ import annotations

import os
import time
from typing import Any, Dict, List

import yaml

from agents.phoenix_authority import PhoenixAuthorityGuard


DEFAULT_LAYERS: List[Dict[str, Any]] = [
    {
        "id": "integration_registry",
        "name": "Research Architecture Registry",
        "status": "complete",
        "purpose": "Inventory external systems and map each one to a Phoenix phase and authority boundary.",
        "systems": ["freqtrade", "hummingbot", "jesse", "nautilus_trader", "hftbacktest"],
        "gates": ["read_only", "authority_contract", "phoenix_phase_mapping"],
    },
    {
        "id": "event_config_spine",
        "name": "Event + Config Spine",
        "status": "complete",
        "purpose": "Provide typed research configuration and end-to-end correlation without live authority.",
        "systems": ["config_agent", "event_spine"],
        "gates": ["schema_validation", "rollback_snapshot", "operator_audit", "protected_field_lock"],
    },
    {
        "id": "external_evidence_import",
        "name": "External Evidence Import",
        "status": "complete",
        "purpose": "Normalize external backtests as unvalidated research imports for Phoenix Phase 2.",
        "systems": ["freqtrade", "jesse", "hummingbot", "hftbacktest"],
        "gates": ["unvalidated_import_only", "no_live_verdict", "phase2_required"],
    },
    {
        "id": "offline_ml_candidates",
        "name": "ML Research Lab",
        "status": "complete",
        "purpose": "Generate offline candidates and model cards for Phoenix research review.",
        "systems": ["freqai", "finrl_crypto", "macrohft", "webcryptoagent"],
        "gates": ["offline_only", "no_wallet_access", "no_execution_authority", "phase2_candidate_only"],
    },
    {
        "id": "execution_reality_audit",
        "name": "Execution Reality Audit",
        "status": "complete",
        "purpose": "Compare predicted, shadow, and realised execution without issuing a parallel promotion verdict.",
        "systems": ["nautilus_trader", "hftbacktest", "execution_parity"],
        "gates": ["diagnostic_only", "phase3_phase5_phase6_comparison", "no_live_authority"],
    },
    {
        "id": "sandbox_strategy_tournament",
        "name": "Signal Marketplace",
        "status": "dormant",
        "purpose": "Score strategy proposals using simulated rewards only after sufficient real outcomes exist.",
        "systems": ["signal_marketplace", "vanta_network", "candles_tao", "time_series_subnet"],
        "gates": ["sandbox_only", "simulated_rewards", "no_promotion_authority"],
    },
    {
        "id": "phase7_1_authority_reconciliation",
        "name": "Phoenix Authority Reconciliation",
        "status": "active",
        "purpose": "Enforce one research-to-live authority chain across all integrations.",
        "systems": ["phoenix_authority", "phase6_canary_operator", "phase7_growth_governor"],
        "gates": ["legacy_submit_denied", "legacy_promote_denied", "legacy_resume_denied", "legacy_scale_denied"],
    },
]


DEFAULT_SYSTEMS: Dict[str, Dict[str, Any]] = {
    "freqtrade": {"role": "external_backtest_benchmark", "adapter_status": "research_only", "phoenix_entry_phase": 2},
    "hummingbot": {"role": "validate_only_execution_reference", "adapter_status": "plan_monitor_stop_only", "phoenix_entry_phase": 3},
    "jesse": {"role": "external_strategy_benchmark", "adapter_status": "research_only", "phoenix_entry_phase": 2},
    "nautilus_trader": {"role": "oms_and_replay_architecture_reference", "adapter_status": "architecture_reference", "phoenix_entry_phase": 3},
    "hftbacktest": {"role": "l2_queue_and_latency_research", "adapter_status": "data_dependent_research", "phoenix_entry_phase": 3},
    "freqai": {"role": "offline_model_candidate", "adapter_status": "offline_only", "phoenix_entry_phase": 2},
    "finrl_crypto": {"role": "offline_rl_candidate", "adapter_status": "offline_only", "phoenix_entry_phase": 2},
    "macrohft": {"role": "offline_microstructure_research", "adapter_status": "offline_only", "phoenix_entry_phase": 2},
    "webcryptoagent": {"role": "research_context_and_explanation", "adapter_status": "offline_only", "phoenix_entry_phase": 2},
    "signal_marketplace": {"role": "sandbox_strategy_tournament", "adapter_status": "dormant_simulated_rewards", "phoenix_entry_phase": 2},
}


class ResearchArchitectureRegistry:
    """Phoenix-aware registry for integration roles, evidence routes, and authority."""

    def __init__(self, cfg: Any, path: str | None = None):
        self.cfg = cfg
        self.path = path or getattr(cfg, "research_architecture_path", "config/research_architecture_layers.yaml")
        self.authority = PhoenixAuthorityGuard()

    def snapshot(self) -> Dict[str, Any]:
        custom = self._load_custom()
        layers = custom.get("layers") or DEFAULT_LAYERS
        systems = dict(DEFAULT_SYSTEMS)
        systems.update(custom.get("systems") or {})
        return {
            "ts": time.time(),
            "version": 2,
            "active_layer": self.active_layer(layers),
            "layers": layers,
            "systems": systems,
            "phoenix_pipeline": [
                "external_research_adapters",
                "phase2_hypothesis_foundry",
                "phase3_execution_lab",
                "phase4_validation_tribunal",
                "phase5_shadow_flight",
                "phase6_canary_operator",
                "phase7_growth_governor",
            ],
            "authority": self.authority.snapshot(),
            "evidence_policy": custom.get("evidence_policy") or self._default_evidence_policy(),
            "next_actions": custom.get("next_actions") or self._default_next_actions(),
        }

    def active_layer(self, layers: List[Dict[str, Any]]) -> Dict[str, Any]:
        for layer in layers:
            if str(layer.get("status") or "").lower() in ("active", "in_progress"):
                return layer
        return layers[-1] if layers else {}

    def _load_custom(self) -> Dict[str, Any]:
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _default_evidence_policy(self) -> Dict[str, Any]:
        return {
            "profit_claims": "untrusted_until_real_phase6_evidence",
            "external_evidence": "unvalidated_import_for_phase2_only",
            "promotion_authority": "phase4_then_phase5_human_review",
            "live_order_authority": "phase6_canary_operator_only",
            "scaling_authority": "phase7_growth_governor_only",
            "legacy_auto_promotion": False,
        }

    def _default_next_actions(self) -> List[str]:
        return [
            "Collect genuine Phase 1 observations",
            "Route external candidates through Phoenix Phase 2",
            "Use execution parity only for model-versus-reality diagnostics",
            "Keep signal marketplace rewards simulated and dormant",
        ]
