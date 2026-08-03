from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from copy import copy
from typing import Any, Mapping, Optional

from .canary_store import CanaryStore
from .growth_models import GrowthApproval, GrowthIncident, GrowthProposal, GrowthStage
from .growth_store import GrowthStore
from .shadow_flight import canonical_hash


PHASE7_ACKNOWLEDGEMENT = "I AUTHORIZE ONE CONTROLLED HIVENANCE GROWTH STAGE"
PHASE7_RECOVERY_ACKNOWLEDGEMENT = "I ACKNOWLEDGE THE PHASE7 INCIDENT AND RESUME AT THE DEMOTED STAGE"
PHASE7_ENV_INTERLOCK = "HIVENANCE_PHASE7_CONTROLLED_GROWTH"

PHASE7_CONFIG_KEYS = (
    "phase7_growth_enabled",
    "phase7_stage_activation_enabled",
    "phase7_max_stage",
    "phase7_proposal_cooldown_sec",
    "phase7_proposal_expiry_sec",
    "phase7_approval_lease_sec",
    "phase7_min_new_round_trips",
    "phase7_min_distinct_days",
    "phase7_require_positive_total_pnl",
    "phase7_min_profit_factor",
    "phase7_max_drawdown_bps",
    "phase7_max_loss_rate",
    "phase7_max_rejection_rate",
    "phase7_max_mean_abs_slippage_bps",
    "phase7_auto_demotion_enabled",
    "phase7_stage_notional_caps_usd",
    "phase7_stage_symbol_caps",
)


def phase7_config_payload(cfg: Any) -> dict[str, Any]:
    return {key: getattr(cfg, key, None) for key in PHASE7_CONFIG_KEYS}


def phase7_config_hash(cfg: Any) -> str:
    return canonical_hash(phase7_config_payload(cfg))


def _list_value(cfg: Any, key: str, default: list[Any]) -> list[Any]:
    raw = getattr(cfg, key, None)
    return list(raw) if isinstance(raw, (list, tuple)) and raw else list(default)


def stage_catalog(cfg: Any) -> tuple[GrowthStage, ...]:
    notionals = [float(x) for x in _list_value(cfg, "phase7_stage_notional_caps_usd", [5.0, 7.5, 10.0, 15.0, 20.0])]
    symbol_caps = [int(x) for x in _list_value(cfg, "phase7_stage_symbol_caps", [1, 1, 2, 2, 3])]
    names = ("CANARY", "EMBER", "FLAME", "WING", "CROWN")
    all_symbols = tuple(str(x) for x in (getattr(cfg, "phase7_allowed_symbols", None) or ["ETH/USD", "BTC/USD", "SOL/USD"]))
    max_stage = max(0, min(int(getattr(cfg, "phase7_max_stage", 4) or 4), 4))
    min_rt = max(10, int(getattr(cfg, "phase7_min_new_round_trips", 50) or 50))
    min_days = max(1, int(getattr(cfg, "phase7_min_distinct_days", 14) or 14))
    stages: list[GrowthStage] = []
    for stage_id in range(max_stage + 1):
        cap_index = min(stage_id, len(notionals) - 1)
        symbol_index = min(stage_id, len(symbol_caps) - 1)
        symbols = all_symbols[: max(1, min(symbol_caps[symbol_index], len(all_symbols)))]
        stages.append(GrowthStage(
            stage_id=stage_id,
            name=names[stage_id],
            max_notional_usd=max(0.01, notionals[cap_index]),
            allowed_symbols=tuple(symbols),
            max_open_orders=1,
            max_open_positions=1,
            daily_loss_halt_usd=max(1.0, notionals[cap_index] * 0.20),
            min_new_round_trips=min_rt,
            min_distinct_days=min_days,
        ))
    return tuple(stages)


def stage_by_id(cfg: Any, stage_id: int) -> GrowthStage:
    stages = stage_catalog(cfg)
    for stage in stages:
        if stage.stage_id == int(stage_id):
            return stage
    raise ValueError(f"unknown Phase-7 stage {stage_id}")


def _closed_positions(canary: CanaryStore, *, since_ts: Optional[float] = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM phase6_canary_positions WHERE status='CLOSED'"
    params: tuple[Any, ...] = ()
    if since_ts is not None:
        query += " AND closed_ts>=?"
        params = (float(since_ts),)
    query += " ORDER BY closed_ts, position_id"
    return canary._fetchall(query, params)


def _order_metrics(canary: CanaryStore, *, since_ts: Optional[float] = None) -> dict[str, Any]:
    query = "SELECT * FROM phase6_canary_orders WHERE live_submitted=1"
    params: tuple[Any, ...] = ()
    if since_ts is not None:
        query += " AND created_ts>=?"
        params = (float(since_ts),)
    rows = canary._fetchall(query + " ORDER BY created_ts", params)
    rejected = [r for r in rows if str(r.get("status") or "").upper() == "REJECTED"]
    unknown = [r for r in rows if str(r.get("status") or "").upper() == "UNKNOWN"]
    slippages: list[float] = []
    for row in rows:
        limit_price = float(row.get("limit_price") or 0.0)
        fill_price = float(row.get("average_fill_price") or 0.0)
        if limit_price <= 0 or fill_price <= 0:
            continue
        side = str(row.get("side") or "buy").lower()
        slip = ((fill_price - limit_price) / limit_price) * 10_000.0
        if side == "sell":
            slip *= -1.0
        slippages.append(abs(slip))
    return {
        "live_order_rows": len(rows),
        "rejected_orders": len(rejected),
        "unknown_orders": len(unknown),
        "rejection_rate": len(rejected) / max(1, len(rows)),
        "mean_abs_slippage_bps": statistics.mean(slippages) if slippages else 0.0,
        "slippage_observations": len(slippages),
    }


def growth_evidence(canary: CanaryStore, growth: GrowthStore, cfg: Any) -> dict[str, Any]:
    state = growth.get_state()
    since_ts = state.get("stage_started_ts") if int(state.get("current_stage", 0) or 0) > 0 else None
    positions = _closed_positions(canary, since_ts=since_ts)
    returns_bps: list[float] = []
    pnls: list[float] = []
    distinct_days: set[int] = set()
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    equity_bps = 0.0
    peak_bps = 0.0
    max_drawdown_bps = 0.0
    for row in positions:
        pnl = float(row.get("realized_pnl_quote") or 0.0)
        cost = max(1e-9, float(row.get("entry_cost_quote") or 0.0))
        pnls.append(pnl)
        trade_return_bps = (pnl / cost) * 10_000.0
        returns_bps.append(trade_return_bps)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)
        closed_ts = float(row.get("closed_ts") or 0.0)
        if closed_ts:
            distinct_days.add(int(closed_ts // 86400))
        equity_bps += trade_return_bps
        peak_bps = max(peak_bps, equity_bps)
        max_drawdown_bps = max(max_drawdown_bps, peak_bps - equity_bps)
    order_metrics = _order_metrics(canary, since_ts=since_ts)
    score = canary.scorecard()
    state_rt = int(state.get("stage_start_round_trips", 0) or 0)
    total_rt = int(score.get("completed_round_trips", 0) or 0)
    new_rt = len(positions) if since_ts is not None else total_rt
    profit_factor = gross_profit / max(1e-12, gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    evidence = {
        "current_stage": int(state.get("current_stage", 0) or 0),
        "stage_state": state.get("state"),
        "stage_started_ts": since_ts,
        "stage_start_round_trips": state_rt,
        "completed_round_trips": total_rt,
        "new_round_trips": new_rt,
        "distinct_days": len(distinct_days),
        "wins": wins,
        "losses": max(0, len(positions) - wins),
        "loss_rate": (len(positions) - wins) / max(1, len(positions)),
        "total_realized_pnl_quote": sum(pnls),
        "mean_return_bps": statistics.mean(returns_bps) if returns_bps else 0.0,
        "median_return_bps": statistics.median(returns_bps) if returns_bps else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown_bps": max_drawdown_bps,
        "open_positions": score.get("open_positions", 0),
        "unknown_order_states": score.get("unknown_orders", 0),
        "open_phase6_incidents": score.get("open_incidents", 0),
        "open_phase7_incidents": len(growth.open_incidents()),
        **order_metrics,
    }
    evidence["evidence_hash"] = canonical_hash(evidence)
    return evidence


def _promotion_gate_reasons(evidence: Mapping[str, Any], cfg: Any, target: GrowthStage) -> list[str]:
    reasons: list[str] = []
    required_rt = int(getattr(cfg, "phase7_min_new_round_trips", target.min_new_round_trips) or target.min_new_round_trips)
    required_days = int(getattr(cfg, "phase7_min_distinct_days", target.min_distinct_days) or target.min_distinct_days)
    if int(evidence.get("new_round_trips", 0) or 0) < required_rt:
        reasons.append("insufficient_new_reconciled_round_trips")
    if int(evidence.get("distinct_days", 0) or 0) < required_days:
        reasons.append("insufficient_distinct_live_days")
    if bool(getattr(cfg, "phase7_require_positive_total_pnl", True)) and float(evidence.get("total_realized_pnl_quote", 0.0) or 0.0) <= 0:
        reasons.append("non_positive_realized_pnl")
    if float(evidence.get("profit_factor", 0.0) or 0.0) < float(getattr(cfg, "phase7_min_profit_factor", 1.05) or 1.05):
        reasons.append("profit_factor_below_gate")
    if float(evidence.get("max_drawdown_bps", 0.0) or 0.0) > float(getattr(cfg, "phase7_max_drawdown_bps", 500.0) or 500.0):
        reasons.append("drawdown_above_gate")
    if float(evidence.get("loss_rate", 0.0) or 0.0) > float(getattr(cfg, "phase7_max_loss_rate", 0.65) or 0.65):
        reasons.append("loss_rate_above_gate")
    if float(evidence.get("rejection_rate", 0.0) or 0.0) > float(getattr(cfg, "phase7_max_rejection_rate", 0.05) or 0.05):
        reasons.append("rejection_rate_above_gate")
    if int(evidence.get("slippage_observations", 0) or 0) and float(evidence.get("mean_abs_slippage_bps", 0.0) or 0.0) > float(getattr(cfg, "phase7_max_mean_abs_slippage_bps", 40.0) or 40.0):
        reasons.append("slippage_above_gate")
    if int(evidence.get("unknown_order_states", 0) or 0):
        reasons.append("unknown_order_state_present")
    if int(evidence.get("open_phase6_incidents", 0) or 0) or int(evidence.get("open_phase7_incidents", 0) or 0):
        reasons.append("unresolved_incident_present")
    if int(evidence.get("open_positions", 0) or 0):
        reasons.append("position_still_open")
    return reasons


def readiness_for_next_stage(canary: CanaryStore, growth: GrowthStore, cfg: Any) -> dict[str, Any]:
    evidence = growth_evidence(canary, growth, cfg)
    state = growth.get_state()
    current = int(state.get("current_stage", 0) or 0)
    stages = stage_catalog(cfg)
    next_stage = current + 1
    reasons: list[str] = []
    if not bool(getattr(cfg, "phase7_growth_enabled", True)):
        reasons.append("phase7_growth_disabled")
    if current >= stages[-1].stage_id:
        reasons.append("maximum_growth_stage_reached")
    target = stages[min(next_stage, stages[-1].stage_id)]
    reasons.extend(_promotion_gate_reasons(evidence, cfg, target))
    if str(state.get("state") or "").upper() in {"HALTED", "DEMOTED", "EXIT_ONLY"}:
        reasons.append("growth_state_not_promotable")
    active = growth.active_proposal()
    if active:
        reasons.append("proposal_or_approval_already_active")
    return {
        "phase": 7,
        "current_stage": current,
        "next_stage": next_stage if next_stage <= stages[-1].stage_id else None,
        "ready_for_next_stage_proposal": not reasons,
        "automatic_promotion": False,
        "execution_scale_authorized": False,
        "human_review_required": True,
        "reasons": reasons,
        "evidence": evidence,
        "target_stage": target.to_dict() if next_stage <= stages[-1].stage_id else None,
    }


def build_growth_proposal(
    canary: CanaryStore,
    growth: GrowthStore,
    cfg: Any,
    *,
    proposed_by: str,
    now_ts: Optional[float] = None,
) -> GrowthProposal:
    proposed_by = str(proposed_by or "").strip()
    if len(proposed_by) < 2:
        raise ValueError("proposed_by must identify the human operator")
    readiness = readiness_for_next_stage(canary, growth, cfg)
    if not readiness["ready_for_next_stage_proposal"]:
        raise ValueError("Phase-7 growth proposal gate is closed: " + ", ".join(readiness["reasons"]))
    now = float(now_ts or time.time())
    cooldown = max(0, int(getattr(cfg, "phase7_proposal_cooldown_sec", 86400) or 0))
    expiry = max(cooldown + 300, int(getattr(cfg, "phase7_proposal_expiry_sec", 604800) or 604800))
    body = {
        "from_stage": readiness["current_stage"],
        "to_stage": readiness["next_stage"],
        "proposed_by": proposed_by,
        "created_ts": now,
        "evidence_hash": readiness["evidence"]["evidence_hash"],
        "config_hash": phase7_config_hash(cfg),
    }
    proposal_id = canonical_hash(body)
    return GrowthProposal(
        proposal_id=proposal_id,
        from_stage=int(readiness["current_stage"]),
        to_stage=int(readiness["next_stage"]),
        proposed_by=proposed_by,
        created_ts=now,
        cooldown_until_ts=now + cooldown,
        expires_ts=now + expiry,
        evidence_hash=readiness["evidence"]["evidence_hash"],
        config_hash=phase7_config_hash(cfg),
        evidence=readiness["evidence"],
    )


def build_growth_approval(
    growth: GrowthStore,
    cfg: Any,
    *,
    approved_by: str,
    acknowledgement: str,
    now_ts: Optional[float] = None,
) -> GrowthApproval:
    approved_by = str(approved_by or "").strip()
    if len(approved_by) < 2:
        raise ValueError("approved_by must identify the human reviewer")
    if acknowledgement != PHASE7_ACKNOWLEDGEMENT:
        raise ValueError("the exact Phase-7 growth acknowledgement is required")
    proposal = growth.active_proposal()
    if not proposal or proposal.get("status") != "PROPOSED":
        raise ValueError("no active Phase-7 proposal awaits approval")
    now = float(now_ts or time.time())
    if now < float(proposal.get("cooldown_until_ts") or 0.0):
        raise ValueError("Phase-7 proposal cooling-off period has not elapsed")
    if now >= float(proposal.get("expires_ts") or 0.0):
        raise ValueError("Phase-7 proposal has expired")
    if str(proposal.get("config_hash") or "") != phase7_config_hash(cfg):
        raise ValueError("Phase-7 configuration drifted after proposal creation")
    current_evidence = growth_evidence(CanaryStore(growth.data_store), growth, cfg)
    target = stage_by_id(cfg, int(proposal.get("to_stage", 0) or 0))
    safety_reasons = _promotion_gate_reasons(current_evidence, cfg, target)
    if safety_reasons:
        growth.reject_active_proposals("approval_safety_recheck_failed:" + ",".join(safety_reasons), now)
        raise ValueError("Phase-7 approval safety recheck failed: " + ", ".join(safety_reasons))
    lease = max(300, min(86400, int(getattr(cfg, "phase7_approval_lease_sec", 3600) or 3600)))
    body = {"proposal_id": proposal["proposal_id"], "approved_by": approved_by, "approved_ts": now}
    approval_id = canonical_hash(body)
    return GrowthApproval(
        approval_id=approval_id,
        proposal_id=str(proposal["proposal_id"]),
        approved_by=approved_by,
        approved_ts=now,
        expires_ts=now + lease,
        acknowledgement_hash=hashlib.sha256(acknowledgement.encode()).hexdigest(),
    )


def activate_approved_stage(canary: CanaryStore, growth: GrowthStore, cfg: Any, *, actor: str, now_ts: Optional[float] = None, env_interlock: Optional[bool] = None) -> dict[str, Any]:
    if not bool(getattr(cfg, "phase7_stage_activation_enabled", False)):
        raise ValueError("selected local profile must explicitly enable Phase-7 stage activation")
    env_ok = os.environ.get(PHASE7_ENV_INTERLOCK, "").strip().upper() == "YES" if env_interlock is None else bool(env_interlock)
    if not env_ok:
        raise ValueError(f"{PHASE7_ENV_INTERLOCK}=YES is required")
    now = float(now_ts or time.time())
    approval = growth.active_approval(now)
    if not approval:
        raise ValueError("no active Phase-7 approval exists")
    proposal = growth.active_proposal()
    if not proposal or proposal.get("status") != "APPROVED" or proposal.get("proposal_id") != approval.get("proposal_id"):
        raise ValueError("approved proposal and approval do not match")
    if str(proposal.get("config_hash") or "") != phase7_config_hash(cfg):
        raise ValueError("Phase-7 configuration drifted after approval")
    target = stage_by_id(cfg, int(proposal["to_stage"]))
    current_evidence = growth_evidence(canary, growth, cfg)
    safety_reasons = _promotion_gate_reasons(current_evidence, cfg, target)
    if safety_reasons:
        growth.reject_active_proposals("activation_safety_recheck_failed:" + ",".join(safety_reasons), now)
        growth.revoke_approval("activation_safety_recheck_failed", now)
        raise ValueError("Phase-7 activation safety recheck failed: " + ", ".join(safety_reasons))
    current_rt = int(canary.scorecard().get("completed_round_trips", 0) or 0)
    envelope_hash = canonical_hash(target.to_dict())
    before = growth.get_state()
    growth.close_active_window(growth_evidence(canary, growth, cfg), status="PROMOTED", now_ts=now)
    growth.set_state(
        "ACTIVE",
        f"human_activated_stage:{target.name}",
        current_stage=target.stage_id,
        stage_started_ts=now,
        stage_start_round_trips=current_rt,
        envelope_hash=envelope_hash,
        payload={"activated_by": actor, "proposal_id": proposal["proposal_id"], "approval_id": approval["approval_id"], "stage": target.to_dict()},
    )
    window_id = canonical_hash({"stage": target.stage_id, "started_ts": now, "proposal_id": proposal["proposal_id"]})
    growth.start_window({
        "window_id": window_id,
        "stage_id": target.stage_id,
        "stage_name": target.name,
        "started_ts": now,
        "start_round_trips": current_rt,
        "status": "ACTIVE",
        "envelope_hash": envelope_hash,
        "result": {},
    })
    growth.consume_approval(str(approval["approval_id"]), now)
    growth.mark_proposal_activated(str(proposal["proposal_id"]), now)
    growth.audit("STAGE_ACTIVATED", actor, before, growth.get_state(), {"stage": target.to_dict()})
    return {"activated": True, "stage": target.to_dict(), "state": growth.get_state(), "automatic_promotion": False}


def resume_demoted_stage(
    canary: CanaryStore,
    growth: GrowthStore,
    cfg: Any,
    *,
    actor: str,
    acknowledgement: str,
    now_ts: Optional[float] = None,
    env_interlock: Optional[bool] = None,
) -> dict[str, Any]:
    actor = str(actor or "").strip()
    if len(actor) < 2:
        raise ValueError("actor must identify the human operator")
    if acknowledgement != PHASE7_RECOVERY_ACKNOWLEDGEMENT:
        raise ValueError("the exact Phase-7 incident recovery acknowledgement is required")
    if not bool(getattr(cfg, "phase7_stage_activation_enabled", False)):
        raise ValueError("selected local profile must explicitly enable Phase-7 stage activation")
    env_ok = os.environ.get(PHASE7_ENV_INTERLOCK, "").strip().upper() == "YES" if env_interlock is None else bool(env_interlock)
    if not env_ok:
        raise ValueError(f"{PHASE7_ENV_INTERLOCK}=YES is required")
    state = growth.get_state()
    if str(state.get("state") or "").upper() not in {"DEMOTED", "HALTED"}:
        raise ValueError("Phase-7 state is not awaiting human recovery")
    if growth.open_incidents():
        raise ValueError("all Phase-7 incidents must be resolved before recovery")
    score = canary.scorecard()
    if int(score.get("unknown_orders", 0) or 0):
        raise ValueError("unknown Phase-6 orders remain unresolved")
    if int(score.get("open_incidents", 0) or 0):
        raise ValueError("Phase-6 incidents remain unresolved")
    if int(score.get("open_positions", 0) or 0) or canary.active_order_count():
        raise ValueError("open Phase-6 risk remains")
    reconciliations = canary.reconciliations(limit=1)
    if not reconciliations or str(reconciliations[0].get("status") or "").upper() != "CLEAN":
        raise ValueError("a fresh CLEAN Phase-6 reconciliation is required")
    now = float(now_ts or time.time())
    current_stage = int(state.get("current_stage", 0) or 0)
    stage = stage_by_id(cfg, current_stage)
    before = dict(state)
    growth.set_state(
        "ACTIVE",
        "human_recovery_at_demoted_stage",
        current_stage=current_stage,
        stage_started_ts=now,
        stage_start_round_trips=int(score.get("completed_round_trips", 0) or 0),
        envelope_hash=canonical_hash(stage.to_dict()),
        payload={"recovered_by": actor, "stage": stage.to_dict(), "reconciliation": reconciliations[0]},
    )
    growth.audit("HUMAN_RECOVERY", actor, before, growth.get_state(), {"stage": stage.to_dict()})
    return {"recovered": True, "stage": stage.to_dict(), "state": growth.get_state(), "automatic_recovery": False}


def stage_capped_config(cfg: Any, growth: GrowthStore) -> Any:
    state = growth.get_state()
    stage = stage_by_id(cfg, int(state.get("current_stage", 0) or 0))
    derived = copy(cfg)
    derived.phase6_max_notional_usd = min(float(getattr(cfg, "phase6_max_notional_usd", stage.max_notional_usd) or stage.max_notional_usd), stage.max_notional_usd)
    # The phase7 runner may use a local profile with a larger Phase-6 ceiling;
    # the growth envelope is always the tighter source of authority.
    if bool(getattr(cfg, "phase7_stage_activation_enabled", False)):
        derived.phase6_max_notional_usd = stage.max_notional_usd
    derived.phase6_allowed_symbols = list(stage.allowed_symbols)
    derived.phase6_max_open_orders = stage.max_open_orders
    derived.phase6_max_open_positions = stage.max_open_positions
    derived.phase6_daily_loss_halt_usd = stage.daily_loss_halt_usd
    return derived


def evaluate_demotion(canary: CanaryStore, growth: GrowthStore, cfg: Any, *, now_ts: Optional[float] = None) -> dict[str, Any]:
    state = growth.get_state()
    current = int(state.get("current_stage", 0) or 0)
    evidence = growth_evidence(canary, growth, cfg)
    triggers: list[str] = []
    if evidence["unknown_order_states"]:
        triggers.append("unknown_order_state")
    if evidence["open_phase6_incidents"] or evidence["open_phase7_incidents"]:
        triggers.append("unresolved_incident")
    if evidence["max_drawdown_bps"] > float(getattr(cfg, "phase7_max_drawdown_bps", 500.0) or 500.0):
        triggers.append("drawdown_breach")
    if evidence["rejection_rate"] > float(getattr(cfg, "phase7_max_rejection_rate", 0.05) or 0.05):
        triggers.append("rejection_rate_breach")
    if evidence["slippage_observations"] and evidence["mean_abs_slippage_bps"] > float(getattr(cfg, "phase7_max_mean_abs_slippage_bps", 40.0) or 40.0):
        triggers.append("slippage_breach")
    if not triggers:
        return {"demoted": False, "triggers": [], "evidence": evidence}
    if not bool(getattr(cfg, "phase7_auto_demotion_enabled", True)):
        return {"demoted": False, "triggers": triggers, "evidence": evidence, "manual_action_required": True}
    now = float(now_ts or time.time())
    new_stage = max(0, current - 1)
    target = stage_by_id(cfg, new_stage)
    incident = GrowthIncident(
        incident_id=canonical_hash({"ts": now, "stage": current, "triggers": triggers}),
        ts=now,
        severity="CRITICAL",
        category="AUTOMATIC_DEMOTION",
        message="Phase-7 stage demoted after safety evidence breach",
        stage_id=current,
        payload={"triggers": triggers, "evidence": evidence, "target_stage": target.to_dict()},
    )
    growth.persist_incident(incident.to_dict())
    growth.reject_active_proposals("automatic_demotion")
    growth.revoke_approval("automatic_demotion", now)
    growth.close_active_window(evidence, status="DEMOTED", now_ts=now)
    growth.set_state(
        "DEMOTED",
        "automatic_safety_demotion:" + ",".join(triggers),
        current_stage=new_stage,
        stage_started_ts=now,
        stage_start_round_trips=int(evidence.get("completed_round_trips", 0)),
        envelope_hash=canonical_hash(target.to_dict()),
        payload={"triggers": triggers, "target_stage": target.to_dict()},
    )
    return {"demoted": True, "from_stage": current, "to_stage": new_stage, "triggers": triggers, "evidence": evidence}


def growth_snapshot(canary: CanaryStore, growth: GrowthStore, cfg: Any, *, limit: int = 50) -> dict[str, Any]:
    state = growth.get_state()
    stage = stage_by_id(cfg, int(state.get("current_stage", 0) or 0))
    return {
        "phase": 7,
        "mode": "controlled_growth_governor",
        "state": state,
        "current_stage": stage.to_dict(),
        "stages": [item.to_dict() for item in stage_catalog(cfg)],
        "readiness": readiness_for_next_stage(canary, growth, cfg),
        "proposals": growth.proposals(limit=limit),
        "approvals": growth.approvals(limit=limit),
        "windows": growth.windows(limit=limit),
        "incidents": growth.open_incidents()[:limit],
        "audit": growth.audit_rows(limit=limit),
        "automatic_promotion": False,
        "automatic_demotion": bool(getattr(cfg, "phase7_auto_demotion_enabled", True)),
        "operator_process_only": True,
        "desktop_stage_activation": False,
        "execution_scale_authorized": state.get("state") == "ACTIVE",
    }
