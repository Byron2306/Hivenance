#!/usr/bin/env python3
"""Mature an existing G1 cohort without creating new G0 twins.

Runs Phase-1 public observation only, then settlement. No hypothesis/G0 generation.
"""
from __future__ import annotations
import argparse,json,os,signal,sys,time
from pathlib import Path
from typing import Any

if os.environ.get("PREFIX") and not os.environ.get("HIVENANCE_G1_PRELOAD_DONE"):
    libpython=Path(os.environ["PREFIX"])/"lib"/f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
    if libpython.exists():
        env=dict(os.environ);existing=env.get("LD_PRELOAD","").strip()
        env["LD_PRELOAD"]=str(libpython) if not existing else str(libpython)+":"+existing
        env["HIVENANCE_G1_PRELOAD_DONE"]="1"
        os.execve(sys.executable,[sys.executable,*sys.argv],env)

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from main import load_config,apply_phase0_safety_policy
from agents.coordinator import SwarmCoordinator
from agents.kraken_public_client import KrakenPublicClient
from strategies.relative_value_lab.g1_campaign_freeze import get_latest_g1_campaign_freeze,policy_from_freeze
from strategies.relative_value_lab.g1_utility_campaign import evaluate_store

STOP=False
def _stop(_s,_f):
 global STOP;STOP=True

def _stop_agents(coordinator:Any)->None:
 for agent in list(getattr(coordinator,"agents",{}).values()):
  stop=getattr(agent,"stop",None)
  if callable(stop):
   try:stop()
   except TypeError:
    try:stop(timeout=1)
    except Exception:pass
   except Exception:pass
 coordinator.running=False

def main()->int:
 ap=argparse.ArgumentParser()
 ap.add_argument("--minutes",type=float,default=65.0)
 ap.add_argument("--pause-sec",type=float,default=45.0)
 ap.add_argument("--quiet-kraken",action="store_true")
 args=ap.parse_args()
 duration=max(60.0,args.minutes*60.0);pause=max(0.0,args.pause_sec)
 signal.signal(signal.SIGINT,_stop);signal.signal(signal.SIGTERM,_stop)

 cfg=apply_phase0_safety_policy(load_config())
 cfg.live_mode=False;cfg.dry_run=True;cfg.phase5_shadow_enabled=True
 cfg.phase6_canary_enabled=False;cfg.phase6_live_submission_enabled=False
 cfg.phase7_growth_enabled=False;cfg.phase7_stage_activation_enabled=False
 cfg.kraken_api_key="";cfg.kraken_api_secret="";cfg.binance_api_key="";cfg.binance_api_secret=""
 client=KrakenPublicClient(progress=not args.quiet_kraken) if str(cfg.exchange).lower()=="kraken" else None
 coordinator=SwarmCoordinator(cfg);coordinator.initialize(client)
 observer=coordinator.agents.get("observation_swarm")
 shadow=coordinator.agents.get("shadow_flight")
 store=coordinator.agents.get("data_store")
 if observer is None or shadow is None or store is None:raise RuntimeError("maturation_components_unavailable")
 campaign=get_latest_g1_campaign_freeze(store)
 if campaign is None:raise RuntimeError("g1_campaign_not_frozen")
 campaign_id=str(campaign.get("campaign_id") or "")
 target_id=str(campaign.get("research_target_id") or "") or None
 policy=policy_from_freeze(campaign)

 print(f"[MATURATION] campaign={campaign_id} target={target_id}",flush=True)
 print(f"[MATURATION] window={duration:.0f}s new_g0_generation=false",flush=True)
 started=time.monotonic();deadline=started+duration;cycles=0
 totals={"examined":0,"settled":0,"deferred":0,"errors":0}
 reasons={"deferred":{},"errors":{}}
 try:
  while not STOP and time.monotonic()<deadline:
   cycles+=1
   print(f"[MATURATION] cycle={cycles} public observation...",flush=True)
   observer.run_once()
   settlement=store.settle_mature_shadow_intents(
    shadow.settler,now_ts=time.time(),
    tolerance_sec=int(getattr(cfg,"phase5_shadow_settlement_tolerance_sec",900) or 900))
   vals={
    "examined":int(settlement.get("g0_twins_examined") or 0),
    "settled":int(settlement.get("g0_twins_settled") or 0),
    "deferred":int(settlement.get("g0_twins_deferred") or 0),
    "errors":int(settlement.get("g0_twin_errors") or 0),
   }
   for k,v in vals.items():totals[k]+=v
   for reason,n in (settlement.get("g0_twin_deferred_reasons") or {}).items():
    reasons["deferred"][str(reason)]=int(reasons["deferred"].get(str(reason)) or 0)+int(n or 0)
   for reason,n in (settlement.get("g0_twin_error_reasons") or {}).items():
    reasons["errors"][str(reason)]=int(reasons["errors"].get(str(reason)) or 0)+int(n or 0)
   reports=evaluate_store(store,policy=policy,campaign_id=campaign_id if target_id else None,target_id=target_id)
   print(f"[MATURATION] cycle={cycles} examined={vals['examined']} settled={vals['settled']} deferred={vals['deferred']} errors={vals['errors']} reports={len(reports)}",flush=True)
   for r in reports:
    print(f"[MATURATION] {r.organ_id} n={r.paired_n} worlds={r.distinct_worlds} mean={r.mean_delta_bps:+.3f} CI=[{r.ci_lower_bps:+.3f},{r.ci_upper_bps:+.3f}] stress={r.stressed_mean_delta_bps:+.3f} {r.classification}",flush=True)
   if time.monotonic()>=deadline or STOP:break
   time.sleep(min(pause,max(0.0,deadline-time.monotonic())))

  reports=[r.to_dict() for r in evaluate_store(store,policy=policy,campaign_id=campaign_id if target_id else None,target_id=target_id)]
  print("G1_MATURATION_RESULT")
  print(json.dumps({
   "campaign_id":campaign_id,"research_target_id":target_id,"cycles":cycles,
   "wall_clock_seconds":round(time.monotonic()-started,3),"settlement_cumulative":totals,
   "settlement_reasons":reasons,"g1_reports":reports,
   "new_g0_generation":False,"execution_wired":False,"private_exchange_access":False,
   "real_orders_submitted":0,"promotion_eligible":False,
  },indent=2,sort_keys=True,default=str))
  return 0
 finally:
  _stop_agents(coordinator)

if __name__=="__main__":raise SystemExit(main())
