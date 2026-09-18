#!/usr/bin/env python3
"""Phoenix Phase-1 observation swarm for the curated on-chain (DEX) token
universe -- the exact same ``ObservationSwarmAgent`` class used for
Kraken/CCXT venues, pointed at ``DexPublicClient`` instead of a CCXT client.

Read-only. No wallet access, no order submission. Persists immutable
observation runs/snapshots into the same ``observation_runs`` /
``observation_snapshots`` tables Kraken Phase 1 uses, tagged with a
``dex_<chain>`` venue (e.g. ``dex_base``), via ``DataStoreAgent``.

Because CEX-tuned defaults (min $5M/24h quote volume, $25k depth-at-25bps,
90-day listing age, etc.) would reject every curated DEX token, this script
overrides the observation thresholds with DEX-appropriate values on its own
in-process config copy only -- it never touches ``config/settings.yaml`` and
has no effect on the Kraken observer process.

IMPORTANT: this writes to a *separate* database file
(``data/swarm_data_dex.db``) by default, not the shared ``swarm_data.db``
Kraken pipeline uses. ``DataStoreAgent.get_hypothesis_scorecard()`` and the
Phase-2/3 DIO gate aggregate across every row in a database with no venue
filter on several rollups, so writing DEX evidence into the same file the
live Kraken go/no-go decision reads from would silently contaminate that
evidence base. Keep these on separate files unless/until the scorecard
functions are made properly venue-aware.
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
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent) -> None:
        self.store = store

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def build_dex_observer_config(
    cfg: Any,
    oracle: DexMarginOracle,
    *,
    timeframe: str,
    lookback: int,
    min_quote_volume_usd: float,
    min_depth_usd_25bps: float,
    max_spread_bps: float,
    min_listing_age_days: float,
    min_data_quality: float,
    gas_safety_buffer_bps: float = 12.0,
    include_symbols: Any = None,
) -> Any:
    universe = oracle.token_universe()
    if include_symbols:
        wanted = {str(s).strip().upper() for s in include_symbols if str(s).strip()}
        if wanted:
            universe = [t for t in universe if str(t.get("symbol", "")).upper() in wanted]
    cfg.exchange = f"dex_{oracle.chain_slug}"
    # venue_profile() zeroes the CEX taker fee for dex_* venues (AMM friction
    # is already priced via the spread/depth proxy) but that leaves gas
    # unaccounted for. Fold a documented, conservative gas-cost estimate into
    # the Phase-2 safety buffer instead of inventing a new cost-model plumbing
    # path. Override with --gas-safety-buffer-bps if real Base gas costs
    # observed via the DEX watcher justify a different number.
    cfg.phase2_safety_buffer_bps = float(gas_safety_buffer_bps)
    cfg.phase1_observation_timeframe = timeframe
    cfg.phase1_observation_lookback = max(61, int(lookback))
    cfg.phase1_observation_max_symbols = max(1, len(universe))
    cfg.phase1_observation_quote_assets = ["USD"]
    cfg.phase1_observation_include = [t["symbol"] for t in universe]
    cfg.phase1_observation_exclude = []
    cfg.phase1_observation_discovery_min_quote_volume_usd = min(1_000.0, min_quote_volume_usd)
    cfg.phase1_observation_min_listing_age_days = float(min_listing_age_days)
    cfg.phase1_observation_min_depth_usd_25bps = float(min_depth_usd_25bps)
    cfg.phase1_observation_min_quote_volume_usd = float(min_quote_volume_usd)
    cfg.phase1_observation_max_spread_bps = float(max_spread_bps)
    cfg.phase1_observation_min_data_quality = float(min_data_quality)
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-1 DEX observation swarm")
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
    parser.add_argument("--interval-sec", type=int, default=300)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    oracle = DexMarginOracle(cfg)
    if not oracle.token_universe():
        print("DEX observer: no onchain_token_addresses configured, nothing to observe", file=sys.stderr)
        return 1
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

    db_path = args.database
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    client = DexPublicClient(cfg, oracle=oracle, quote_symbol="USD")
    store = DataStoreAgent(str(db_path))
    observer = ObservationSwarmAgent(cfg, client, coordinator=StoreBridge(store))

    def collect() -> None:
        payload = observer.run_once()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            run = payload.get("run") or {}
            print(
                f"{payload.get('status')} venue={run.get('venue')} run={run.get('run_id')} "
                f"observed={run.get('symbols_successful', 0)}/{run.get('symbols_attempted', 0)} "
                f"eligible={run.get('symbols_eligible', 0)} "
                f"quality={float(run.get('mean_data_quality') or 0):.3f} orders=0"
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
            print(f"DEX observation cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
