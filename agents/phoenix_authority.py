from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


PROTECTED_ACTIONS = {
    "submit_order",
    "transmit_order",
    "promote_live",
    "resume_live",
    "scale_capital",
    "mutate_frozen_config",
    "grant_execution_authority",
    "activate_live_sidecar",
}

RESEARCH_ACTIONS = {
    "observe",
    "import_evidence",
    "normalize_evidence",
    "score_candidate",
    "generate_proposal",
    "simulate_execution",
    "diagnose_execution",
    "render_status",
    "configure_research",
    "stop_research_process",
}

COMPONENT_ROLES: Dict[str, Dict[str, Any]] = {
    "research_architecture": {
        "role": "architecture_registry",
        "mode": "read_only",
        "phoenix_entry_phase": 0,
    },
    "config_agent": {
        "role": "research_configuration_administrator",
        "mode": "research_only",
        "phoenix_entry_phase": 0,
    },
    "event_spine": {
        "role": "event_correlation_transport",
        "mode": "telemetry_only",
        "phoenix_entry_phase": 0,
    },
    "evidence_registry": {
        "role": "external_evidence_normalizer",
        "mode": "unvalidated_import_only",
        "phoenix_entry_phase": 2,
    },
    "ml_research_lab": {
        "role": "offline_candidate_generator",
        "mode": "offline_only",
        "phoenix_entry_phase": 2,
    },
    "execution_parity": {
        "role": "model_vs_reality_auditor",
        "mode": "diagnostic_only",
        "phoenix_entry_phase": 3,
    },
    "signal_marketplace": {
        "role": "sandbox_strategy_tournament",
        "mode": "simulated_rewards_only",
        "phoenix_entry_phase": 2,
    },
    "public_bot_bridge": {
        "role": "external_research_adapter",
        "mode": "research_only",
        "phoenix_entry_phase": 2,
    },
    "public_bot_backtests": {
        "role": "external_backtest_importer",
        "mode": "unvalidated_import_only",
        "phoenix_entry_phase": 2,
    },
    "hummingbot_lifecycle": {
        "role": "validate_only_execution_reference",
        "mode": "plan_monitor_stop_only",
        "phoenix_entry_phase": 3,
    },
    "market_making_advisors": {
        "role": "offline_quote_advisor",
        "mode": "advisory_only",
        "phoenix_entry_phase": 2,
    },
}


@dataclass(frozen=True)
class AuthorityDecision:
    component: str
    action: str
    allowed: bool
    reason: str
    authority_owner: str
    mode: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "authority_owner": self.authority_owner,
            "mode": self.mode,
        }


class PhoenixAuthorityGuard:
    """Single authority map for legacy integrations.

    Legacy agents may observe, normalize, simulate, diagnose, and propose. They
    may never submit an order, promote a strategy to live, resume a halted live
    system, or scale capital. Phase 6 owns live order authority. Phase 7 owns
    capital-stage authority.
    """

    version = "phase7.1-authority-v1"

    def decision(self, component: str, action: str) -> AuthorityDecision:
        component = str(component or "unknown").strip().lower()
        action = str(action or "unknown").strip().lower()
        role = COMPONENT_ROLES.get(component, {
            "role": "unregistered_component",
            "mode": "deny_by_default",
            "phoenix_entry_phase": None,
        })
        if action in PROTECTED_ACTIONS:
            owner = "phase7_growth_governor" if action == "scale_capital" else "phase6_canary_operator"
            return AuthorityDecision(
                component=component,
                action=action,
                allowed=False,
                reason="phoenix_authority_locked",
                authority_owner=owner,
                mode=str(role.get("mode") or "deny_by_default"),
            )
        if action in RESEARCH_ACTIONS and component in COMPONENT_ROLES:
            return AuthorityDecision(
                component=component,
                action=action,
                allowed=True,
                reason="research_or_diagnostic_action",
                authority_owner="phoenix_pipeline",
                mode=str(role.get("mode") or "research_only"),
            )
        return AuthorityDecision(
            component=component,
            action=action,
            allowed=False,
            reason="unregistered_or_unsupported_action",
            authority_owner="phoenix_pipeline",
            mode=str(role.get("mode") or "deny_by_default"),
        )

    def assert_allowed(self, component: str, action: str) -> AuthorityDecision:
        decision = self.decision(component, action)
        if not decision.allowed:
            raise PermissionError(
                f"{decision.component}:{decision.action} denied: {decision.reason}; "
                f"authority owner={decision.authority_owner}"
            )
        return decision

    def component_contract(self, component: str) -> Dict[str, Any]:
        component = str(component or "unknown").strip().lower()
        role = dict(COMPONENT_ROLES.get(component) or {})
        return {
            "component": component,
            **role,
            "execution_authority": "none",
            "promotion_authority": "none",
            "resume_authority": "none",
            "scaling_authority": "none",
            "live_allowed": False,
            "allowed_actions": sorted(RESEARCH_ACTIONS),
            "denied_actions": sorted(PROTECTED_ACTIONS),
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "version": self.version,
            "single_authority_chain": True,
            "sole_live_order_authority": "phase6_canary_operator",
            "sole_scaling_authority": "phase7_growth_governor",
            "legacy_automatic_promotion": False,
            "legacy_automatic_recovery": False,
            "components": {
                name: self.component_contract(name)
                for name in sorted(COMPONENT_ROLES)
            },
        }
