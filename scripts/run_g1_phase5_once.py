#!/usr/bin/env python3
from __future__ import annotations
import json,sys,os
from pathlib import Path

# Termux/Python 3.14: cryptography Rust bindings can fail to resolve Python C-API
# symbols unless libpython is preloaded before interpreter startup.
if os.environ.get("PREFIX") and not os.environ.get("HIVENANCE_G1_PRELOAD_DONE"):
    libpython=Path(os.environ["PREFIX"])/"lib"/f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
    if libpython.exists():
        env=dict(os.environ)
        existing=env.get("LD_PRELOAD","").strip()
        env["LD_PRELOAD"]=str(libpython) if not existing else str(libpython)+":"+existing
        env["HIVENANCE_G1_PRELOAD_DONE"]="1"
        os.execve(sys.executable,[sys.executable,*sys.argv],env)
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from main import load_config,apply_phase0_safety_policy
from agents.coordinator import SwarmCoordinator
from agents.kraken_public_client import KrakenPublicClient

def main()->int:
 print("[G1] loading research config...",flush=True)
 cfg=apply_phase0_safety_policy(load_config())
 # This launcher is intentionally stricter than the ordinary research coordinator.
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
 print(f"[G1] mode exchange={cfg.exchange} dry_run={cfg.dry_run} phase5={cfg.phase5_shadow_enabled}",flush=True)
 client=KrakenPublicClient(progress=True) if str(cfg.exchange).lower()=="kraken" else None
 print("[G1] initializing coordinator...",flush=True)
 coordinator=SwarmCoordinator(cfg)
 coordinator.initialize(client)
 print("[G1] coordinator initialized",flush=True)
 shadow=coordinator.agents.get("shadow_flight")
 if shadow is None:
  raise RuntimeError("shadow_flight_agent_unavailable")
 print("[G1] starting one Phase-5 shadow cycle with upstream public observation...",flush=True)
 payload=shadow.run_once(drive_upstream=True)
 print("[G1] Phase-5 cycle returned",flush=True)
 g1=payload.get("g1_organ_utility") or {}
 phase2=((payload.get("upstream_cycle") or {}).get("phase2_cycle") or {})
 print("G1_PHASE5_ONCE")
 print(json.dumps({
  "status":payload.get("status"),
  "run_id":payload.get("run_id"),
  "g0_prospective":phase2.get("g0_prospective"),
  "settlement":payload.get("settlement"),
  "g1_campaign_freeze":g1.get("campaign_freeze"),
  "g1_report_count":g1.get("report_count"),
  "g1_utility_candidates":g1.get("utility_candidates"),
  "g1_error":g1.get("error"),
  "execution_wired":False,
  "private_exchange_access":False,
  "real_orders_submitted":0,
 },indent=2,sort_keys=True,default=str))
 return 0

if __name__=="__main__":raise SystemExit(main())
