from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from .canary_lab import phase6_spot_freeze_compatibility


COST_RANK = {"none": 0, "cheap": 1, "normal": 2, "expensive": 3, "human": 99}


@dataclass(frozen=True)
class GovernorAction:
    action: str
    cost_class: str
    reason: str
    command: list[str] = field(default_factory=list)
    requires_human: bool = False
    safe_to_auto_execute: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GovernorDecision:
    schema: str
    last_control_gate: str
    real_evidence_gate: str
    current_blocker: str
    next_action: GovernorAction
    observations: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["next_action"] = self.next_action.to_dict()
        return payload


def _phase_decision(truth: Mapping[str, Any], phase: int) -> str:
    phases = truth.get("phases") if isinstance(truth.get("phases"), Mapping) else {}
    payload = phases.get(str(phase)) if isinstance(phases, Mapping) else {}
    return str((payload or {}).get("decision") or "REFUSE").upper()


def _phase_reasons(truth: Mapping[str, Any], phase: int) -> list[str]:
    phases = truth.get("phases") if isinstance(truth.get("phases"), Mapping) else {}
    payload = phases.get(str(phase)) if isinstance(phases, Mapping) else {}
    return [str(item) for item in ((payload or {}).get("reasons") or [])]


def _phase_metrics(truth: Mapping[str, Any], phase: int) -> dict[str, Any]:
    phases = truth.get("phases") if isinstance(truth.get("phases"), Mapping) else {}
    payload = phases.get(str(phase)) if isinstance(phases, Mapping) else {}
    metrics = (payload or {}).get("metrics") or {}
    return dict(metrics) if isinstance(metrics, Mapping) else {}


def real_evidence_gate(truth: Mapping[str, Any]) -> str:
    highest = 0
    for phase in range(1, 6):
        if _phase_decision(truth, phase) == "ALLOW":
            highest = phase
            continue
        break
    return f"phase{highest}" if highest else "none"


def phase6_control_gate(soak_report: Optional[Mapping[str, Any]]) -> str:
    if not soak_report:
        return "unproven"
    try:
        campaign = soak_report.get("campaign") or {}
        gate = campaign.get("phase7_review_gate") or {}
        sabotage = soak_report.get("ambiguity_sabotage") or {}
        if (
            campaign.get("kind") == "deterministic_fake_exchange_safety_control"
            and campaign.get("market_profitability_evidence") is False
            and int(campaign.get("network_calls") or 0) == 0
            and bool(gate.get("ready_for_phase7_review"))
            and int(campaign.get("legacy_orders_rows") or 0) == 0
            and int(campaign.get("legacy_fills_rows") or 0) == 0
            and int(campaign.get("unknown_orders") or 0) == 0
            and int(campaign.get("open_incidents") or 0) == 0
            and sabotage.get("first_status") == "HALTED"
            and sabotage.get("second_status") == "HALTED"
            and int(sabotage.get("add_calls_after_two_cycles") or 0) == 1
        ):
            return "phase6_control"
    except Exception:
        return "unproven"
    return "unproven"


def _champion_freeze_like(truth: Mapping[str, Any]) -> dict[str, Any]:
    champion = _phase_metrics(truth, 4).get("champion") or {}
    if not isinstance(champion, Mapping):
        return {}
    scope = champion.get("candidate_scope") if isinstance(champion.get("candidate_scope"), Mapping) else {}
    return {
        "freeze_id": "",
        "candidate_key": str(champion.get("candidate_key") or ""),
        "model_id": str(champion.get("model_id") or scope.get("model_id") or ""),
        "order_policy": str(champion.get("order_policy") or scope.get("order_policy") or ""),
        "symbol": str(champion.get("symbol") or scope.get("symbol") or ""),
        "direction": str(champion.get("direction") or scope.get("direction") or ""),
    }


def _common_command(
    root: Path,
    script: str,
    *,
    settings: Path,
    exchange: str,
    profile: Optional[Path] = None,
    database: Optional[Path] = None,
    extra: Optional[list[str]] = None,
) -> list[str]:
    command = [sys.executable, str(root / script), "--settings", str(settings), "--exchange", exchange]
    if profile:
        command.extend(["--profile", str(profile)])
    if database:
        command.extend(["--database", str(database)])
    command.extend(extra or [])
    return command


def _small_window_freeze(freeze: Mapping[str, Any]) -> bool:
    candidate_key = str((freeze or {}).get("candidate_key") or "")
    model_id = str((freeze or {}).get("model_id") or "")
    return (
        model_id == "small_window_trend_comparison_v1"
        or candidate_key.startswith("small_window_trend_comparison_v1|")
    )


def _small_window_trend_command(root: Path, *, profile: Optional[Path], database: Optional[Path]) -> list[str]:
    command = [
        sys.executable,
        str(root / "scripts/run_small_window_trend_tape.py"),
    ]
    if profile:
        command.extend(["--profile", str(profile)])
    if database:
        command.extend(["--database", str(database)])
    command.extend(["--limit", "12", "--raise-open-cap", "8"])
    return command


def _phase6_canary_once_command(
    root: Path,
    *,
    settings: Path,
    profile: Optional[Path],
    database: Optional[Path],
) -> list[str]:
    command = [
        sys.executable,
        str(root / "scripts/run_phase6_canary.py"),
        "--settings",
        str(settings),
        "--once",
        "--json",
    ]
    if profile:
        command.extend(["--profile", str(profile)])
    if database:
        command.extend(["--database", str(database)])
    return command


def decide_next_action(
    *,
    truth: Mapping[str, Any],
    cfg: Any,
    root: Path,
    settings: Path,
    exchange: str,
    active_freeze: Optional[Mapping[str, Any]] = None,
    phase6_soak_report: Optional[Mapping[str, Any]] = None,
    profile: Optional[Path] = None,
    database: Optional[Path] = None,
) -> GovernorDecision:
    active_freeze = dict(active_freeze or {})
    safety = truth.get("safety") if isinstance(truth.get("safety"), Mapping) else {}
    control_gate = phase6_control_gate(phase6_soak_report)
    real_gate = real_evidence_gate(truth)
    p4_decision = _phase_decision(truth, 4)
    p5_decision = _phase_decision(truth, 5)
    freeze_compatibility = phase6_spot_freeze_compatibility(active_freeze, cfg)
    champion_compatibility = phase6_spot_freeze_compatibility(_champion_freeze_like(truth), cfg)
    observations = {
        "phase_decisions": {str(phase): _phase_decision(truth, phase) for phase in range(1, 6)},
        "phase4_reasons": _phase_reasons(truth, 4),
        "phase5_reasons": _phase_reasons(truth, 5),
        "active_freeze": active_freeze,
        "active_freeze_compatibility": freeze_compatibility,
        "phase4_champion_compatibility": champion_compatibility,
        "phase6_control_gate": control_gate,
    }

    if str(safety.get("status") or "CLEAN").upper() != "CLEAN":
        action = GovernorAction(
            action="STOP_SAFETY_ALERT",
            cost_class="none",
            reason="current_truth_safety_status_is_not_clean",
            requires_human=True,
        )
        return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "safety_alert", action, observations)

    if (
        p5_decision == "ALLOW"
        and freeze_compatibility.get("canary_compatible")
        and freeze_compatibility.get("rapid_paper_canary")
    ):
        action = GovernorAction(
            action="RUN_PHASE6_RAPID_PAPER_CANARY",
            cost_class="cheap",
            reason="phase5_ready_and_active_small_window_freeze_can_run_non_live_directional_canary",
            command=_phase6_canary_once_command(root, settings=settings, profile=profile, database=database),
            safe_to_auto_execute=True,
        )
        return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "phase6_rapid_paper_canary_ready", action, observations)

    if p5_decision == "ALLOW" and freeze_compatibility.get("canary_compatible"):
        action = GovernorAction(
            action="REQUEST_PHASE6_CANARY_APPROVAL",
            cost_class="human",
            reason="phase5_ready_and_active_freeze_is_phase6_spot_compatible",
            command=_common_command(
                root,
                "scripts/run_phase6_canary.py",
                settings=settings,
                exchange=exchange,
                profile=profile,
                database=database,
                extra=["--approve-canary", "--approved-by", "<human>", "--acknowledgement", "<exact_phrase>"],
            ),
            requires_human=True,
        )
        return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "phase6_human_approval_required", action, observations)

    if active_freeze and not freeze_compatibility.get("canary_compatible") and _small_window_freeze(active_freeze):
        action = GovernorAction(
            action="RUN_SMALL_WINDOW_TREND_TAPE",
            cost_class="cheap",
            reason="active_small_window_freeze_is_shadow_research_only_until_a_spot_long_slice_repeats",
            command=_small_window_trend_command(root, profile=profile, database=database),
            safe_to_auto_execute=True,
        )
        return GovernorDecision(
            "hivenance_acceptance_governor_v1",
            control_gate,
            real_gate,
            "small_window_shadow_only_not_phase6_spot_compatible",
            action,
            observations,
        )

    if active_freeze and not freeze_compatibility.get("canary_compatible"):
        action = GovernorAction(
            action="RUN_PHASE4_VALIDATION_ONLY",
            cost_class="expensive",
            reason="active_phase5_freeze_cannot_feed_phase6_spot_canary",
            command=_common_command(
                root,
                "scripts/run_phase4_validation.py",
                settings=settings,
                exchange=exchange,
                profile=profile,
                database=database,
                extra=["--once", "--validate-only"],
            ),
            safe_to_auto_execute=True,
        )
        return GovernorDecision(
            "hivenance_acceptance_governor_v1",
            control_gate,
            real_gate,
            "active_phase5_freeze_not_phase6_compatible",
            action,
            observations,
        )

    if p5_decision != "ALLOW":
        if active_freeze and freeze_compatibility.get("canary_compatible"):
            action = GovernorAction(
                action="RUN_PHASE5_SHADOW_ONLY",
                cost_class="cheap",
                reason="compatible_phase5_freeze_exists_but_shadow_evidence_is_incomplete",
                command=_common_command(
                    root,
                    "scripts/run_phase5_shadow_flight.py",
                    settings=settings,
                    exchange=exchange,
                    profile=profile,
                    database=database,
                    extra=["--once", "--shadow-only"],
                ),
                safe_to_auto_execute=True,
            )
            return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "phase5_shadow_evidence_incomplete", action, observations)

        if p4_decision == "ALLOW" and champion_compatibility.get("canary_compatible"):
            action = GovernorAction(
                action="REQUEST_PHASE5_FREEZE_APPROVAL",
                cost_class="human",
                reason="phase4_passed_with_phase6_compatible_champion",
                command=_common_command(
                    root,
                    "scripts/run_phase5_shadow_flight.py",
                    settings=settings,
                    exchange=exchange,
                    profile=profile,
                    database=database,
                    extra=["--approve-current-champion", "--approved-by", "<human>"],
                ),
                requires_human=True,
            )
            return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "phase5_freeze_approval_required", action, observations)

        if _phase_decision(truth, 3) == "ALLOW":
            action = GovernorAction(
                action="RUN_PHASE4_VALIDATION_ONLY",
                cost_class="expensive",
                reason="phase3_allows_but_no_phase6_compatible_phase4_champion_is_currently_proven",
                command=_common_command(
                    root,
                    "scripts/run_phase4_validation.py",
                    settings=settings,
                    exchange=exchange,
                    profile=profile,
                    database=database,
                    extra=["--once", "--validate-only"],
                ),
                safe_to_auto_execute=True,
            )
            return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "phase4_compatible_champion_needed", action, observations)

        if _phase_decision(truth, 2) == "ALLOW":
            action = GovernorAction(
                action="RUN_PHASE3_REPLAY_ONLY",
                cost_class="normal",
                reason="phase2_allows_but_phase3_evidence_gate_is_not_currently_open",
                command=_common_command(
                    root,
                    "scripts/run_phase3_execution_lab.py",
                    settings=settings,
                    exchange=exchange,
                    profile=profile,
                    database=database,
                    extra=["--once", "--replay-only", "--compact-scorecard"],
                ),
                safe_to_auto_execute=True,
            )
            return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "phase3_replay_needed", action, observations)

        if _phase_decision(truth, 1) == "ALLOW":
            action = GovernorAction(
                action="RUN_PHASE2_SETTLE_ONLY",
                cost_class="cheap",
                reason="phase1_allows_but_phase2_evidence_gate_is_not_currently_open",
                command=_common_command(
                    root,
                    "scripts/run_phase2_hypotheses.py",
                    settings=settings,
                    exchange=exchange,
                    profile=profile,
                    database=database,
                    extra=["--once", "--settle-only", "--compact-scorecard"],
                ),
                safe_to_auto_execute=True,
            )
            return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "phase2_settlement_needed", action, observations)

    action = GovernorAction(
        action="WAIT_FOR_NEW_OBSERVATIONS",
        cost_class="none",
        reason="no_safe_useful_research_action_was_available",
        safe_to_auto_execute=False,
    )
    return GovernorDecision("hivenance_acceptance_governor_v1", control_gate, real_gate, "waiting", action, observations)


def load_phase6_soak_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def can_execute(action: GovernorAction, max_cost: str) -> bool:
    if not action.safe_to_auto_execute or action.requires_human or not action.command:
        return False
    return COST_RANK.get(action.cost_class, 99) <= COST_RANK.get(max_cost, 0)
