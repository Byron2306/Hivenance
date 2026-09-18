#!/usr/bin/env python3
"""Phoenix Phase-4 adversarial validator for the curated on-chain (DEX)
token universe -- reuses ``ValidationLabAgent`` unmodified, the exact same
class the Kraken Phase-4 runner uses, fed by the DEX Phase-1/2/3 stack
(``ObservationSwarmAgent`` + ``HypothesisSwarmAgent`` + ``ExecutionLabAgent``
+ ``DexPublicClient``) instead of a CCXT client.

Read-only/simulation-only research, same as the Kraken Phase-4 validator --
no wallet access, no order submission.

IMPORTANT: writes to a *separate* database file (``data/swarm_data_dex.db``
by default), never the shared ``swarm_data.db`` the live Kraken pipeline's
scorecard/DIO-gate decision reads from. See ``run_phase1_observer_dex.py``
for why that isolation matters.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from agents.dex_margin_oracle import DexMarginOracle
from agents.dex_public_client import DexPublicClient
from scripts.run_phase1_observer import load_observer_config
from scripts.run_phase1_observer_dex import build_dex_observer_config
from strategies.volatility_breakout.execution_lab import ExecutionLabAgent
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent
from strategies.volatility_breakout.validation_lab import ValidationLabAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent, cfg: Any | None = None) -> None:
        self.store = store
        self.cfg = cfg

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-4 DEX adversarial validator")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path, default=ROOT / "data/swarm_data_dex.db")
    parser.add_argument("--timeframe", default="15m", choices=["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"])
    parser.add_argument("--lookback", type=int, default=96)
    parser.add_argument("--min-quote-volume-usd", type=float, default=25_000.0)
    parser.add_argument("--min-depth-usd-25bps", type=float, default=500.0)
    parser.add_argument("--max-spread-bps", type=float, default=300.0)
    parser.add_argument("--min-listing-age-days", type=float, default=1.0)
    parser.add_argument("--min-data-quality", type=float, default=0.75)
    parser.add_argument("--gas-safety-buffer-bps", type=float, default=12.0)
    parser.add_argument(
        "--symbols",
        default="",
        help="comma-separated symbol allowlist (e.g. AERO,CBBTC); default is the full curated universe",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--bootstrap-samples", type=int)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate existing Phase-3 evidence without fetching public data or creating new simulations",
    )
    parser.add_argument("--interval-sec", type=int, default=900)
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    oracle = DexMarginOracle(cfg)
    if not oracle.token_universe():
        print("DEX Phase-4: no onchain_token_addresses configured, nothing to validate", file=sys.stderr)
        return 1
    cfg.phase2_hypotheses_enabled = True
    cfg.phase3_execution_lab_enabled = True
    cfg.phase4_validation_enabled = True
    cfg = build_dex_observer_config(
        cfg,
        oracle,
        timeframe=args.timeframe,
        lookback=args.lookback,
        min_quote_volume_usd=args.min_quote_volume_usd,
        min_depth_usd_25bps=args.min_depth_usd_25bps,
        max_spread_bps=args.max_spread_bps,
        min_listing_age_days=args.min_listing_age_days,
        min_data_quality=args.min_data_quality,
        gas_safety_buffer_bps=args.gas_safety_buffer_bps,
        include_symbols=[s for s in args.symbols.split(",") if s.strip()] if args.symbols else None,
    )
    if args.max_rows:
        cfg.phase4_max_rows = max(100, int(args.max_rows))
    if args.bootstrap_samples:
        cfg.phase4_bootstrap_samples = max(100, int(args.bootstrap_samples))

    db_path = args.database
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    bridge = StoreBridge(None, cfg)
    store = DataStoreAgent(str(db_path), coordinator=bridge)
    bridge.store = store
    execution_lab = None
    if not args.validate_only:
        client = DexPublicClient(cfg, oracle=oracle, quote_symbol="USD")
        observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
        hypothesis = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)
        execution_lab = ExecutionLabAgent(cfg, hypothesis, store, coordinator=bridge)
    validator = ValidationLabAgent(cfg, execution_lab, store, coordinator=bridge)

    def collect() -> None:
        payload = validator.run_once(drive_phase3=not args.validate_only)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            readiness = payload.get("readiness") or {}
            pbo = payload.get("pbo") or {}
            champion = payload.get("champion") or {}
            print(
                f"{payload.get('status')} run={payload.get('run_id')} "
                f"rows={payload.get('rows_examined', 0)} candidates={payload.get('candidate_count', 0)} "
                f"pbo={pbo.get('pbo_estimate', 1.0):.3f} "
                f"champion={champion.get('candidate_key', 'none')} "
                f"phase5_review={bool(readiness.get('ready_for_phase5_review'))} real_orders=0"
            )

    if args.once:
        collect()
        return 0

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    interval = max(60, int(args.interval_sec))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"DEX Phase-4 cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
