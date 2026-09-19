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
    "relative_value_pair_lab": {
        "role": "pair_relationship_research",
        "mode": "research_only",
        "phoenix_entry_phase": 2,
    },
    "relative_value_microstructure": {
        "role": "public_microstructure_observer",
        "mode": "telemetry_only",
        "phoenix_entry_phase": 1,
    },
    "relative_value_forecaster": {
        "role": "forward_relative_return_forecaster",
        "mode": "research_only",
        "phoenix_entry_phase": 2,
    },
    "relative_value_research_council": {
        "role": "local_advisory_inference",
        "mode": "advisory_only",
        "phoenix_entry_phase": 2,
    },
    "relative_value_harmonic_governance": {
        "role": "forecast_coherence_and_dissent_governor",
        "mode": "research_filter_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_market_hunting": {
        "role": "proactive_market_hypothesis_hunter",
        "mode": "research_discovery_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_colony_correlation": {
        "role": "cross_pair_temporal_correlation_engine",
        "mode": "research_correlation_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_ml_challenger": {
        "role": "learned_forecast_challenger",
        "mode": "offline_and_walk_forward_research_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_edge_chorus": {
        "role": "research_transition_companion_and_settlement_verifier",
        "mode": "research_edge_governance_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_notation_token": {
        "role": "world_state_bound_single_use_research_transition_token",
        "mode": "research_transition_authority_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_harmony_law": {
        "role": "constitutional_bee_testimony_validator",
        "mode": "fail_closed_research_governance_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_waggle_protocol": {
        "role": "harmony_gated_interorgan_hypothesis_bus",
        "mode": "append_only_research_communication",
        "phoenix_entry_phase": 4,
    },
    "relative_value_musical_cognition": {
        "role": "rhythm_cadence_counterpoint_and_motif_listener",
        "mode": "continuous_music_only_research_cognition",
        "phoenix_entry_phase": 4,
    },
    "relative_value_polyphonic_entrainment": {
        "role": "independent_voice_phase_alignment_and_crescendo_listener",
        "mode": "descriptive_music_only_research_cognition",
        "phoenix_entry_phase": 4,
    },
    "relative_value_governance_epoch": {
        "role": "world_state_bound_score_key_and_genre_context",
        "mode": "research_score_governance_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_conducting_queen": {
        "role": "vns_listening_triune_score_and_notation_conductor",
        "mode": "continuous_polyphonic_research_conductor",
        "phoenix_entry_phase": 4,
    },
    "relative_value_temporal_texture": {
        "role": "jitter_burstiness_entropy_and_cadence_texture_listener",
        "mode": "descriptive_temporal_research_cognition",
        "phoenix_entry_phase": 4,
    },
    "relative_value_causal_cascade": {
        "role": "evidence_bound_propagation_phrase_builder",
        "mode": "research_propagation_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_hive_pulse": {
        "role": "decaying_colony_accent_and_scope_signal",
        "mode": "research_attention_and_safety_pulse_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_polyphonic_resonance": {
        "role": "directionless_cross_register_resonance_listener",
        "mode": "descriptive_polyphonic_research_cognition",
        "phoenix_entry_phase": 4,
    },
    "relative_value_mystique": {
        "role": "sealed_synthetic_theme_and_variations_falsifier",
        "mode": "synthetic_counterfactual_research_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_cognitive_metabolism": {
        "role": "context_tool_confidence_and_information_burn_listener",
        "mode": "descriptive_research_metabolism_only",
        "phoenix_entry_phase": 4,
    },
    "relative_value_world_score": {
        "role": "canonical_observed_market_score_page_and_binding_root",
        "mode": "immutable_observed_research_context",
        "phoenix_entry_phase": 4,
    },
    "relative_value_vns_score_conductor": {
        "role": "public_observation_measure_compiler_and_sensory_accent_conductor",
        "mode": "continuous_public_market_research_listening",
        "phoenix_entry_phase": 4,
    },
    "relative_value_graph": {
        "role": "pair_graph_research",
        "mode": "research_only",
        "phoenix_entry_phase": 2,
    },
    "relative_value_execution_lab": {
        "role": "paper_execution_research",
        "mode": "simulation_only",
        "phoenix_entry_phase": 3,
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