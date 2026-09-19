#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from main import load_config,apply_phase0_safety_policy
from agents.coordinator import SwarmCoordinator

def main()->int:
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
 client=None
 if str(cfg.exchange).lower()=="kraken":
  try:
   import ccxt
   client=ccxt.kraken({"enableRateLimit":True})
  except Exception as exc:
   print(f"PUBLIC_CLIENT_WARNING: {type(exc).__name__}: {exc}")
 coordinator=SwarmCoordinator(cfg)
 coordinator.initialize(client)
 shadow=coordinator.agents.get("shadow_flight")
 if shadow is None:
  raise RuntimeError("shadow_flight_agent_unavailable")
 payload=shadow.run_once(drive_upstream=True)
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
