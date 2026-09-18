#!/usr/bin/env python3
"""Phoenix Phase-3 execution-aware simulator for the curated on-chain (DEX)
token universe -- reuses ``ExecutionLabAgent`` unmodified, the exact same
class the Kraken Phase-3 runner uses, fed by the DEX Phase-1/2 stack
(``ObservationSwarmAgent`` + ``HypothesisSwarmAgent`` + ``DexPublicClient``)
instead of a CCXT client.

It is structurally unable to submit a private exchange/wallet order -- same
as the Kraken Phase-3 lab, this is simulation-only research.

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

LARGE_DB_COMPACT_THRESHOLD_BYTES = 512 * 1024 * 1024

from agents.data_store_agent import DataStoreAgent
from agents.dex_margin_oracle import DexMarginOracle
from agents.dex_public_client import DexPublicClient
from scripts.run_phase1_observer import load_observer_config
from scripts.run_phase1_observer_dex import build_dex_observer_config
from strategies.volatility_breakout.execution_lab import ExecutionLabAgent
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent, cfg: Any | None = None) -> None:
        self.store = store
        self.cfg = cfg

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-3 DEX execution-aware simulator")
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
    parser.add_argument("--max-forecasts", type=int)
    parser.add_argument("--model-id")
    parser.add_argument("--model-prefix")
    parser.add_argument(
        "--compact-scorecard",
        action="store_true",
        help="use bounded recent Phase-3 scorecard/readiness reporting for large ledgers",
    )
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="simulate already settled Phase-2 forecasts without fetching new public data",
    )
    parser.add_argument("--interval-sec", type=int, default=120)
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    oracle = DexMarginOracle(cfg)
    if not oracle.token_universe():
        print("DEX Phase-3: no onchain_token_addresses configured, nothing to evaluate", file=sys.stderr)
        return 1
    cfg.phase2_hypotheses_enabled = True
    cfg.phase3_execution_lab_enabled = True
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
    if args.max_forecasts:
        cfg.phase3_max_forecasts_per_cycle = max(1, int(args.max_forecasts))
    if args.model_id:
        cfg.phase3_candidate_model_id = str(args.model_id)
    if args.model_prefix:
        cfg.phase3_candidate_model_prefix = str(args.model_prefix)

    db_path = args.database
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    auto_compact_scorecard = False
    try:
        auto_compact_scorecard = db_path.exists() and db_path.stat().st_size >= LARGE_DB_COMPACT_THRESHOLD_BYTES
    except OSError:
        auto_compact_scorecard = False

    bridge = StoreBridge(None, cfg)
    store = DataStoreAgent(str(db_path), coordinator=bridge)
    bridge.store = store
    hypothesis = None
    if not args.replay_only:
        client = DexPublicClient(cfg, oracle=oracle, quote_symbol="USD")
        observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
        hypothesis = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)
    lab = ExecutionLabAgent(cfg, hypothesis, store, coordinator=bridge)

    def collect() -> None:
        payload = lab.run_once(drive_phase2=not args.replay_only)
        compact_mode = bool(args.compact_scorecard or auto_compact_scorecard)
        if compact_mode:
            from strategies.volatility_breakout.current_truth import _compact_phase3_readiness, _compact_phase3_scorecard

            scorecard = _compact_phase3_scorecard(
                store,
                require_verified_fees=bool(getattr(cfg, "phase3_require_verified_fees", False)),
            )
            readiness = _compact_phase3_readiness(
                scorecard,
                min_completed=int(getattr(cfg, "phase3_readiness_min_completed", 100) or 100),
                max_mean_2x_loss_bps=float(getattr(cfg, "phase3_readiness_max_mean_2x_loss_bps", 50.0) or 50.0),
            )
        else:
            scorecard = store.get_execution_scorecard()
            readiness = store.get_phase3_readiness(
                min_completed=int(getattr(cfg, "phase3_readiness_min_completed", 100) or 100),
                max_mean_2x_loss_bps=float(
                    getattr(cfg, "phase3_readiness_max_mean_2x_loss_bps", 50.0) or 50.0
                ),
                scorecard=scorecard,
            )
        commons = store.get_commons_phase_summary(3, limit=50)
        payload["readiness"] = {key: value for key, value in readiness.items() if key != "scorecard"}
        payload["dio_gate"] = store.build_dio_gate_snapshot_from_evidence(
            3, readiness=readiness, scorecard=scorecard, commons=commons,
        )
        store.persist_simulation_run(payload)
        if args.json:
            print(json.dumps(
                {"cycle": payload, "scorecard": scorecard, "readiness": readiness},
                indent=2, sort_keys=True, default=str,
            ))
        else:
            run = payload.get("run") or {}
            print(
                f"{payload.get('status')} run={run.get('run_id')} "
                f"forecasts={run.get('forecasts_examined', 0)} "
                f"simulations={run.get('simulations_created', 0)} "
                f"completed={run.get('completed', 0)} rejected={run.get('rejected', 0)} "
                f"expired={run.get('expired', 0)} gate={payload['dio_gate'].get('decision')} "
                f"compact={1 if compact_mode else 0} real_orders=0"
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
    interval = max(30, int(args.interval_sec))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"DEX Phase-3 cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
