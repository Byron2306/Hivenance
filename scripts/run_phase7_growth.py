#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from scripts.run_phase6_canary import build_private_client
from strategies.volatility_breakout.canary_lab import PHASE6_ACKNOWLEDGEMENT, TinyLiveCanary, build_canary_approval
from strategies.volatility_breakout.canary_store import CanaryStore
from strategies.volatility_breakout.growth_lab import (
    PHASE7_ACKNOWLEDGEMENT,
    PHASE7_ENV_INTERLOCK,
    PHASE7_RECOVERY_ACKNOWLEDGEMENT,
    activate_approved_stage,
    build_growth_approval,
    build_growth_proposal,
    evaluate_demotion,
    growth_snapshot,
    resume_demoted_stage,
    stage_capped_config,
)
from strategies.volatility_breakout.growth_store import GrowthStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-7 controlled-growth governor")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path, default=ROOT / "config/volatility_breakout_phase7.yaml")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--propose-next-stage", action="store_true")
    parser.add_argument("--proposed-by")
    parser.add_argument("--approve-growth", action="store_true")
    parser.add_argument("--approved-by")
    parser.add_argument("--ack-growth-risk")
    parser.add_argument("--activate-growth", action="store_true")
    parser.add_argument("--approve-next-entry", action="store_true")
    parser.add_argument("--ack-live-risk")
    parser.add_argument("--revoke-growth-approval", action="store_true")
    parser.add_argument("--resolve-growth-incident")
    parser.add_argument("--resolution")
    parser.add_argument("--resume-demoted-stage", action="store_true")
    parser.add_argument("--ack-recovery-risk")
    parser.add_argument("--halt", action="store_true")
    parser.add_argument("--demote-now", action="store_true")
    parser.add_argument("--reason", default="human_operator_action")
    parser.add_argument("--reconcile-only", action="store_true")
    parser.add_argument("--emergency-cancel-all", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/swarm_data.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    data_store = DataStoreAgent(str(db_path))
    canary_store = CanaryStore(data_store)
    growth_store = GrowthStore(data_store)

    if args.propose_next_stage:
        if not args.proposed_by:
            parser.error("--proposed-by is required")
        proposal = build_growth_proposal(canary_store, growth_store, cfg, proposed_by=args.proposed_by)
        growth_store.persist_proposal(proposal.to_dict())
        print(json.dumps({
            "proposed": True,
            "proposal": proposal.to_dict(),
            "warning": "This proposal grants no execution authority and cannot be approved until its cooling-off period expires.",
        }, indent=2, sort_keys=True, default=str))
        return 0

    if args.approve_growth:
        if not args.approved_by:
            parser.error("--approved-by is required")
        if args.ack_growth_risk != PHASE7_ACKNOWLEDGEMENT:
            parser.error(f"--ack-growth-risk must exactly equal: {PHASE7_ACKNOWLEDGEMENT!r}")
        approval = build_growth_approval(
            growth_store,
            cfg,
            approved_by=args.approved_by,
            acknowledgement=args.ack_growth_risk,
        )
        growth_store.persist_approval(approval.to_dict())
        growth_store.mark_proposal_approved(approval.proposal_id, approval.approved_ts)
        print(json.dumps({
            "approved": True,
            "approval": approval.to_dict(),
            "warning": "Approval is temporary and still requires the separate Phase-7 activation interlock.",
        }, indent=2, sort_keys=True, default=str))
        return 0

    if args.activate_growth:
        actor = str(args.approved_by or "").strip()
        if len(actor) < 2:
            parser.error("--approved-by is required to identify the activating human")
        result = activate_approved_stage(canary_store, growth_store, cfg, actor=actor)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0

    if args.revoke_growth_approval:
        changed = growth_store.revoke_approval(args.reason)
        growth_store.reject_active_proposals("human_revocation:" + args.reason)
        print(json.dumps({"revoked": bool(changed), "reason": args.reason}, indent=2))
        return 0 if changed else 1

    if args.resolve_growth_incident:
        if not args.resolution:
            parser.error("--resolution is required")
        changed = growth_store.resolve_incident(args.resolve_growth_incident, args.resolution)
        print(json.dumps({"resolved": changed, "incident_id": args.resolve_growth_incident, "resolution": args.resolution}, indent=2))
        return 0 if changed else 1

    if args.resume_demoted_stage:
        if not args.approved_by:
            parser.error("--approved-by is required")
        if args.ack_recovery_risk != PHASE7_RECOVERY_ACKNOWLEDGEMENT:
            parser.error(f"--ack-recovery-risk must exactly equal: {PHASE7_RECOVERY_ACKNOWLEDGEMENT!r}")
        result = resume_demoted_stage(
            canary_store,
            growth_store,
            cfg,
            actor=args.approved_by,
            acknowledgement=args.ack_recovery_risk,
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0

    if args.halt:
        growth_store.set_state("HALTED", "manual_halt:" + args.reason)
        canary_store.set_state("HALTED", "phase7_manual_halt:" + args.reason)
        print(json.dumps({"halted": True, "reason": args.reason}, indent=2))
        return 0

    if args.demote_now:
        state = growth_store.get_state()
        current = int(state.get("current_stage", 0) or 0)
        target = max(0, current - 1)
        growth_store.reject_active_proposals("manual_demotion")
        growth_store.revoke_approval("manual_demotion")
        growth_store.set_state(
            "DEMOTED",
            "manual_demotion:" + args.reason,
            current_stage=target,
            stage_started_ts=time.time(),
            stage_start_round_trips=int(canary_store.scorecard().get("completed_round_trips", 0) or 0),
        )
        canary_store.set_state("HALTED", "phase7_manual_demotion:" + args.reason)
        print(json.dumps({"demoted": True, "from_stage": current, "to_stage": target, "reason": args.reason}, indent=2))
        return 0

    capped_cfg = stage_capped_config(cfg, growth_store)

    if args.approve_next_entry:
        state = growth_store.get_state()
        if state.get("state") != "ACTIVE":
            parser.error("Phase-7 stage must be ACTIVE before approving another entry")
        if not args.approved_by:
            parser.error("--approved-by is required")
        if args.ack_live_risk != PHASE6_ACKNOWLEDGEMENT:
            parser.error(f"--ack-live-risk must exactly equal: {PHASE6_ACKNOWLEDGEMENT!r}")
        approval = build_canary_approval(
            data_store,
            capped_cfg,
            approved_by=args.approved_by,
            acknowledgement=args.ack_live_risk,
        )
        canary_store.persist_approval(approval.to_dict())
        print(json.dumps({
            "approved": True,
            "entry_approval": approval.to_dict(),
            "stage": growth_snapshot(canary_store, growth_store, cfg, limit=1)["current_stage"],
            "warning": "One entry only. The growth stage does not remove the per-entry human lease.",
        }, indent=2, sort_keys=True, default=str))
        return 0

    client = build_private_client(capped_cfg)
    canary = TinyLiveCanary(capped_cfg, data_store, client)

    if args.status:
        print(json.dumps(growth_snapshot(canary_store, growth_store, cfg), indent=2, sort_keys=True, default=str))
        return 0

    if args.live:
        if args.once:
            parser.error("--live cannot be combined with --once; controlled growth requires continuous supervised operation")
        state = growth_store.get_state()
        if state.get("state") != "ACTIVE" or int(state.get("current_stage", 0) or 0) < 1:
            parser.error("an explicitly activated Phase-7 stage is required before live controlled-growth operation")
        if not bool(getattr(cfg, "phase7_stage_activation_enabled", False)):
            parser.error("the selected local profile must set phase7_stage_activation_enabled: true")
        if os.environ.get(PHASE7_ENV_INTERLOCK, "").strip().upper() != "YES":
            parser.error(f"{PHASE7_ENV_INTERLOCK}=YES is required")
        if not bool(getattr(capped_cfg, "phase6_live_submission_enabled", False)):
            parser.error("the selected local profile must set phase6_live_submission_enabled: true")
        if os.environ.get("HIVENANCE_PHASE6_LIVE_SUBMISSION", "").strip().upper() != "YES":
            parser.error("HIVENANCE_PHASE6_LIVE_SUBMISSION=YES is required")
        if client is None:
            parser.error("HIVENANCE_KRAKEN_API_KEY and HIVENANCE_KRAKEN_API_SECRET are required")

    if args.emergency_cancel_all:
        if client is None:
            parser.error("Kraken environment credentials are required")
        result = client.cancel_all()
        growth_store.set_state("HALTED", "emergency_cancel_all_invoked", payload=result)
        canary_store.set_state("HALTED", "phase7_emergency_cancel_all_invoked", payload=result)
        print(json.dumps({"canceled": True, "result": result, "state": "HALTED"}, indent=2, default=str))
        return 0

    if args.reconcile_only:
        if client is None:
            parser.error("Kraken environment credentials are required")
        try:
            result = canary.reconcile()
        except Exception as exc:
            growth_store.set_state("HALTED", f"reconciliation_exception:{type(exc).__name__}", payload={"error": str(exc)})
            print(json.dumps({"status": "HALTED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
            return 2
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0

    def cycle() -> dict[str, Any]:
        demotion = evaluate_demotion(canary_store, growth_store, cfg)
        if demotion.get("demoted"):
            canary_store.set_state("HALTED", "phase7_automatic_demotion", payload=demotion)
            return {"status": "DEMOTED", "growth": demotion, "canary": canary.snapshot()}
        result = canary.run_once(live_requested=args.live)
        after = evaluate_demotion(canary_store, growth_store, cfg)
        if after.get("demoted"):
            canary_store.set_state("HALTED", "phase7_automatic_demotion", payload=after)
        return {"status": after.get("demoted") and "DEMOTED" or result.get("status"), "canary": result, "growth": growth_snapshot(canary_store, growth_store, cfg, limit=10)}

    if args.once:
        result = cycle()
        print(json.dumps(result, indent=2, sort_keys=True, default=str) if args.json else result.get("status"))
        return 0

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    interval = max(5, int(getattr(capped_cfg, "phase6_deadman_refresh_sec", 20) or 20))
    while not stopping:
        started = time.monotonic()
        try:
            result = cycle()
            if args.json:
                print(json.dumps(result, indent=2, sort_keys=True, default=str))
            else:
                stage = result.get("growth", {}).get("current_stage", {}) if isinstance(result.get("growth"), dict) else {}
                print(f"{result.get('status')} stage={stage.get('name', 'LOCKED')} max_notional={stage.get('max_notional_usd', 5.0)}")
            if result.get("status") == "DEMOTED":
                stopping = True
        except Exception as exc:
            growth_store.set_state("HALTED", f"operator_process_exception:{type(exc).__name__}", payload={"error": str(exc)})
            canary_store.set_state("HALTED", f"phase7_operator_exception:{type(exc).__name__}", payload={"error": str(exc)})
            print(f"Phase-7 growth cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            stopping = True
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))

    if args.live and client is not None:
        cleanup: dict[str, Any] = {"pending_orders_canceled": False}
        try:
            cleanup["cancel_all_result"] = client.cancel_all()
            cleanup["pending_orders_canceled"] = True
        except Exception as exc:
            cleanup["cancel_all_error"] = f"{type(exc).__name__}: {exc}"
        open_position = canary_store.get_open_position()
        if open_position:
            growth_store.set_state("EXIT_ONLY", "operator_process_stopped_with_open_spot_inventory", payload={"position": open_position, "cleanup": cleanup})
            canary_store.set_state("EXIT_ONLY", "phase7_operator_stopped_with_open_spot_inventory", payload={"position": open_position, "cleanup": cleanup})
            print("CRITICAL: Phase-7 operator stopped with open spot inventory. Reconcile and close the position before any restart.", file=sys.stderr)
            return 3
        growth_store.set_state("HALTED", "operator_process_stopped", payload=cleanup)
        canary_store.set_state("HALTED", "phase7_operator_process_stopped", payload=cleanup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
