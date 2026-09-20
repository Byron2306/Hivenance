#!/usr/bin/env python3
"""Run one continuous live-public G1 prospective gauntlet.

Research-only:
- public Kraken observations
- no credentials/private endpoints
- no order transmission
- no execution or promotion authority
- frozen G1 campaign/target reused unchanged throughout the run
"""
from __future__ import annotations
import argparse,json,os,signal,sys,time
from collections import defaultdict
from pathlib import Path
from typing import Any

# Termux/Python 3.14 cryptography Rust-binding safeguard.
if os.environ.get("PREFIX") and not os.environ.get("HIVENANCE_G1_PRELOAD_DONE"):
    libpython=Path(os.environ["PREFIX"])/"lib"/f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
    if libpython.exists():
        env=dict(os.environ)
        existing=env.get("LD_PRELOAD","").strip()
        env["LD_PRELOAD"]=str(libpython) if not existing else str(libpython)+":"+existing
        env["HIVENANCE_G1_PRELOAD_DONE"]="1"
        os.execve(sys.executable,[sys.executable,*sys.argv],env)

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from main import load_config,apply_phase0_safety_policy
from agents.coordinator import SwarmCoordinator
from agents.kraken_public_client import KrakenPublicClient
from strategies.relative_value_lab.g1_campaign_freeze import (
    freeze_g1_campaign,
    get_latest_g1_campaign_freeze,
)
from strategies.relative_value_lab.g1_research_target import (
    ensure_g1_research_target,
    get_latest_g1_research_target,
)
from strategies.relative_value_lab.g1_utility_campaign import G1CampaignPolicy

STOP=False

def _signal_stop(_sig,_frame):
    global STOP
    STOP=True

def _find_key(value:Any,key:str):
    if isinstance(value,dict):
        if key in value:return value[key]
        for child in value.values():
            found=_find_key(child,key)
            if found is not None:return found
    elif isinstance(value,(list,tuple)):
        for child in value:
            found=_find_key(child,key)
            if found is not None:return found
    return None

def _merge_counts(total:dict[str,Any],g0:dict[str,Any])->None:
    total["features_examined"]+=int(g0.get("features_examined") or 0)
    for key in ("eligible","diverged","frozen","skipped","errors"):
        total[key]+=int(g0.get(key) or 0)
    for organ_id,counts in (g0.get("by_organ") or {}).items():
        bucket=total["by_organ"].setdefault(str(organ_id),{
            "examined":0,"eligible":0,"diverged":0,"frozen":0,"skipped":0,"errors":0,
            "raw_non_abstain":0,"raw_abstain":0,"raw_abstain_reasons":{},
        })
        for key in ("examined","eligible","diverged","frozen","skipped","errors","raw_non_abstain","raw_abstain"):
            bucket[key]+=int((counts or {}).get(key) or 0)
        for reason,n in ((counts or {}).get("raw_abstain_reasons") or {}).items():
            bucket["raw_abstain_reasons"][str(reason)]=int(bucket["raw_abstain_reasons"].get(str(reason)) or 0)+int(n or 0)

def _stop_agents(coordinator:Any)->None:
    for agent in list(getattr(coordinator,"agents",{}).values()):
        stop=getattr(agent,"stop",None)
        if not callable(stop):continue
        try:stop()
        except TypeError:
            try:stop(timeout=1)
            except Exception:pass
        except Exception:pass
    coordinator.running=False

def _compact_cycle(n:int,elapsed:float,g0:dict[str,Any],settlement:dict[str,Any],status:str,phase13:dict[str,Any]|None=None)->None:
    organs=g0.get("by_organ") or {}
    influenced={k:int(v.get("diverged") or 0) for k,v in organs.items() if int(v.get("diverged") or 0)>0}
    acted={k:int(v.get("raw_non_abstain") or 0) for k,v in organs.items() if int(v.get("raw_non_abstain") or 0)>0}
    print(
        f"[GAUNTLET] cycle={n} elapsed={elapsed:.1f}s "
        f"features={int(g0.get('features_examined') or 0)} "
        f"eligible={int(g0.get('eligible') or 0)} "
        f"raw_non_abstain={sum(int(v.get('raw_non_abstain') or 0) for v in organs.values())} "
        f"diverged={int(g0.get('diverged') or 0)} frozen={int(g0.get('frozen') or 0)} "
        f"twins_settled={int((settlement or {}).get('g0_twins_settled') or 0)} "
        f"phase13_rows={int((phase13 or {}).get('book_rows') or 0)} "
        f"phase13_inserts={int((phase13 or {}).get('inserted') or 0)} "
        f"phase13_errors={int((phase13 or {}).get('errors') or 0)} "
        f"status={status}",
        flush=True,
    )
    if acted: print("[GAUNTLET] raw_non_abstain_by_organ="+json.dumps(acted,sort_keys=True),flush=True)
    if influenced: print("[GAUNTLET] divergence_by_organ="+json.dumps(influenced,sort_keys=True),flush=True)

def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--minutes",type=float,default=15.0)
    parser.add_argument("--pause-sec",type=float,default=5.0,
        help="minimum pause between completed cycles; cycle runtime itself counts toward wall clock")
    parser.add_argument("--quiet-kraken",action="store_true",
        help="hide individual Kraken request lines")
    args=parser.parse_args()
    duration=max(60.0,float(args.minutes)*60.0)
    pause=max(0.0,float(args.pause_sec))

    signal.signal(signal.SIGINT,_signal_stop)
    signal.signal(signal.SIGTERM,_signal_stop)

    print("[GAUNTLET] loading research config...",flush=True)
    cfg=apply_phase0_safety_policy(load_config())
    cfg.live_mode=False
    cfg.dry_run=True
    cfg.phase5_shadow_enabled=True
    cfg.phase6_canary_enabled=False
    cfg.phase6_live_submission_enabled=False
    cfg.phase7_growth_enabled=False
    cfg.phase7_stage_activation_enabled=False
    cfg.kraken_api_key=""
    cfg.kraken_api_secret=""
    cfg.binance_api_key=""
    cfg.binance_api_secret=""

    client=KrakenPublicClient(progress=not args.quiet_kraken) if str(cfg.exchange).lower()=="kraken" else None
    coordinator=SwarmCoordinator(cfg)
    print(f"[GAUNTLET] initializing coordinator exchange={cfg.exchange} dry_run={cfg.dry_run}",flush=True)
    coordinator.initialize(client)
    shadow=coordinator.agents.get("shadow_flight")
    store=coordinator.agents.get("data_store")
    if shadow is None:raise RuntimeError("shadow_flight_agent_unavailable")
    if store is None:raise RuntimeError("canonical_data_store_unavailable")

    target=get_latest_g1_research_target(store)
    if target is None:
        target=ensure_g1_research_target(store,cfg,created_ts=time.time())
        print("[GAUNTLET] bootstrapped research target="+str(target.get("target_id")),flush=True)

    campaign=get_latest_g1_campaign_freeze(store)
    if campaign is None:
        policy=G1CampaignPolicy(
            min_pairs=int(getattr(cfg,"g1_min_pairs",30) or 30),
            confidence_z=float(getattr(cfg,"g1_confidence_z",1.96) or 1.96),
            extra_cost_stress_bps=float(getattr(cfg,"g1_extra_cost_stress_bps",5.0) or 5.0),
            min_mean_delta_bps=float(getattr(cfg,"g1_min_mean_delta_bps",0.0) or 0.0),
            max_delta_drawdown_bps=float(getattr(cfg,"g1_max_delta_drawdown_bps",250.0) or 250.0),
            min_distinct_worlds=int(getattr(cfg,"g1_min_distinct_worlds",10) or 10),
        )
        campaign=freeze_g1_campaign(
            store,
            policy=policy,
            organs=(
                "edge_ecology",
                "horizon_context",
                "temporal_participation_bee",
                "learning_memory",
                "comparison_engine",
                "polyphonic_quorum",
                "conducting_queen",
            ),
            created_ts=time.time(),
        )
        print("[GAUNTLET] bootstrapped campaign="+str(campaign.get("campaign_id")),flush=True)

    if campaign.get("research_target_id") and str(campaign.get("research_target_id"))!=str(target.get("target_id")):
        raise RuntimeError("latest_campaign_target_mismatch")

    print("[GAUNTLET] campaign="+str(campaign.get("campaign_id")),flush=True)
    print("[GAUNTLET] target="+str(target.get("target_id"))+" models="+json.dumps(target.get("model_ids") or [target.get("model_id")]),flush=True)
    print(f"[GAUNTLET] LIVE PUBLIC RESEARCH WINDOW {duration:.0f}s",flush=True)

    started=time.monotonic()
    deadline=started+duration
    cycles=0
    total={
        "features_examined":0,"eligible":0,"diverged":0,"frozen":0,"skipped":0,"errors":0,
        "by_organ":{},
    }
    settlements={"g0_twins_examined":0,"g0_twins_settled":0,"g0_twins_deferred":0,"g0_twin_errors":0,
                 "settled":0,"missed_fills":0,"adversarial_courts_created":0,
                 "adversarial_court_errors":0}
    settlement_reasons={"errors":{},"deferred":{}}
    last_payload=None
    cycle_errors=[]
    last_cycle_runtime=None

    try:
        while not STOP and time.monotonic()<deadline:
            cycle_start=time.monotonic()
            remaining=max(0.0,deadline-cycle_start)
            minimum_budget=max(30.0,(last_cycle_runtime or 0.0)*1.10)
            if cycles>0 and remaining<minimum_budget:
                print(f"[GAUNTLET] no new full observation cycle: remaining={remaining:.1f}s budget={minimum_budget:.1f}s",flush=True)
                while not STOP and time.monotonic()<deadline:
                    sleep_for=min(5.0,max(0.0,deadline-time.monotonic()))
                    if sleep_for<=0:break
                    time.sleep(sleep_for)
                break
            cycles+=1
            print(f"[GAUNTLET] cycle={cycles} start remaining={remaining:.1f}s",flush=True)
            try:
                payload=shadow.run_once(drive_upstream=True)
                last_payload=payload
                g0=_find_key(payload.get("upstream_cycle") or {},"g0_prospective") or {}
                settlement=payload.get("settlement") or {}
                _merge_counts(total,g0)
                for key in settlements:
                    settlements[key]+=int(settlement.get(key) or 0)
                last_cycle_runtime=time.monotonic()-cycle_start
                phase13=_find_key(payload.get("upstream_cycle") or {},"phase13_books") or {}
                _compact_cycle(cycles,time.monotonic()-started,g0,settlement,str(payload.get("status") or ""),phase13)
                print(f"[GAUNTLET] cycle={cycles} runtime={last_cycle_runtime:.1f}s",flush=True)
            except Exception as exc:
                cycle_errors.append(f"cycle_{cycles}:{type(exc).__name__}:{exc}")
                total["errors"]+=1
                print(f"[GAUNTLET] cycle={cycles} ERROR {type(exc).__name__}: {exc}",flush=True)

            now=time.monotonic()
            if now>=deadline or STOP:break
            sleep_for=min(pause,max(0.0,deadline-now))
            if sleep_for>0:
                print(f"[GAUNTLET] pause={sleep_for:.1f}s",flush=True)
                time.sleep(sleep_for)

        # Final settlement-only pass. Do not create a fresh observation after deadline.
        print("[GAUNTLET] final settlement pass...",flush=True)
        try:
            payload=shadow.run_once(drive_upstream=False)
            last_payload=payload
            settlement=payload.get("settlement") or {}
            for key in settlements:
                settlements[key]+=int(settlement.get(key) or 0)
            for reason,n in (settlement.get("g0_twin_error_reasons") or {}).items():
                settlement_reasons["errors"][str(reason)]=int(settlement_reasons["errors"].get(str(reason)) or 0)+int(n or 0)
            for reason,n in (settlement.get("g0_twin_deferred_reasons") or {}).items():
                settlement_reasons["deferred"][str(reason)]=int(settlement_reasons["deferred"].get(str(reason)) or 0)+int(n or 0)
        except Exception as exc:
            cycle_errors.append(f"final_settlement:{type(exc).__name__}:{exc}")

        elapsed=time.monotonic()-started
        final_campaign=(last_payload or {}).get("g1_organ_utility") or {}
        result={
            "schema":"hivenance_g1_live_gauntlet_v1",
            "wall_clock_seconds":round(elapsed,3),
            "requested_seconds":duration,
            "cycles_completed":cycles,
            "interrupted":bool(STOP),
            "campaign_id":campaign.get("campaign_id"),
            "research_target_id":target.get("target_id"),
            "research_models":target.get("model_ids") or ([target.get("model_id")] if target.get("model_id") else []),
            "g0_cumulative":total,
            "settlement_cumulative":settlements,
            "settlement_reasons":settlement_reasons,
            "g1_reports":final_campaign.get("reports") or [],
            "g1_report_count":final_campaign.get("report_count"),
            "g1_utility_candidates":final_campaign.get("utility_candidates"),
            "g1_error":final_campaign.get("error"),
            "cycle_errors":cycle_errors,
            "execution_wired":False,
            "private_exchange_access":False,
            "real_orders_submitted":0,
            "promotion_eligible":False,
        }
        print("G1_LIVE_GAUNTLET_RESULT")
        print(json.dumps(result,indent=2,sort_keys=True,default=str))
        return 0 if not cycle_errors else 2
    finally:
        print("[GAUNTLET] stopping agents...",flush=True)
        _stop_agents(coordinator)
        print("[GAUNTLET] done",flush=True)

if __name__=="__main__":
    raise SystemExit(main())
