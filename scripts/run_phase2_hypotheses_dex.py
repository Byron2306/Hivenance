#!/usr/bin/env python3
"""Phoenix Phase-2 hypothesis competition for the curated on-chain (DEX)
token universe -- reuses ``HypothesisSwarmAgent`` unmodified, the exact same
class the Kraken Phase-2 runner uses, fed by ``ObservationSwarmAgent`` +
``DexPublicClient`` instead of a CCXT client.

Read-only research. No wallet access, no order submission.

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
from scripts.run_phase1_observer_dex import build_dex_observer_config
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.current_truth import (
    _compact_phase2_readiness,
    _materialized_compact_phase2_scorecard,
)
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent


class StoreBridge:
    def __init__(self, store: DataStoreAgent) -> None:
        self.store = store

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-2 DEX hypothesis competition")
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
    parser.add_argument("--settle-only", action="store_true")
    parser.add_argument("--compact-scorecard", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--compact-limit", type=int, default=20000)
    parser.add_argument("--interval-sec", type=int, default=300)
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    cfg.phase2_hypotheses_enabled = True
    oracle = DexMarginOracle(cfg)
    if not oracle.token_universe():
        print("DEX Phase-2: no onchain_token_addresses configured, nothing to evaluate", file=sys.stderr)
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

    store = DataStoreAgent(str(db_path))
    bridge = StoreBridge(store)
    swarm = None
    if not args.settle_only:
        client = DexPublicClient(cfg, oracle=oracle, quote_symbol="USD")
        observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
        swarm = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)

    def collect() -> None:
        compact_mode = bool(args.compact_scorecard)
        scorecard_context = (
            _materialized_compact_phase2_scorecard(store, cfg, limit=int(args.compact_limit))
            if compact_mode
            else store.get_hypothesis_scorecard()
        )
        payload = None if args.settle_only else swarm.run_once(scorecard_context=scorecard_context)
        settlement = (
            {"examined": 0, "settled": 0, "pending": 0, "skipped": "report_only"}
            if args.report_only
            else store.settle_mature_hypothesis_forecasts(
                tolerance_sec=float(getattr(cfg, "phase2_settlement_tolerance_sec", 600) or 600),
                limit=max(1, int(getattr(cfg, "phase2_settlement_batch_limit", 500) or 500)),
                min_target_ts=(
                    time.time() - float(getattr(cfg, "phase2_settlement_max_backlog_age_sec", 6 * 3600) or 6 * 3600)
                ),
                abandon_after_sec=float(getattr(cfg, "phase2_settlement_abandon_after_sec", 3600) or 3600),
            )
        )
        evidence_changed = payload is not None or int(settlement.get("settled") or 0) > 0
        scorecard = (
            (
                _materialized_compact_phase2_scorecard(store, cfg, limit=int(args.compact_limit), force=True)
                if compact_mode
                else store.get_hypothesis_scorecard()
            )
            if evidence_changed
            else scorecard_context
        )
        readiness = (
            _compact_phase2_readiness(store, scorecard, limit=int(args.compact_limit))
            if compact_mode
            else store.get_phase2_readiness(
                min_forecasts=int(getattr(cfg, "phase2_readiness_min_forecasts", 300) or 300),
                min_settled_non_abstain=int(getattr(cfg, "phase2_readiness_min_settled_non_abstain", 100) or 100),
                min_distinct_days=int(getattr(cfg, "phase2_readiness_min_distinct_days", 14) or 14),
                distinct_bucket_hours=int(getattr(cfg, "phase2_readiness_distinct_snapshot_bucket_hours", 24) or 24),
                scorecard=scorecard,
            )
        )
        commons = store.get_commons_phase_summary(2, limit=50)
        dio_gate = store.build_dio_gate_snapshot_from_evidence(
            2, readiness=readiness, scorecard=scorecard, commons=commons,
        )
        if payload is not None:
            payload["readiness"] = {key: value for key, value in readiness.items() if key != "scorecard"}
            payload["dio_gate"] = dio_gate
            store.handle_event({
                "buzz": {"type": "buzz.hypothesis.snapshot", "source": "PHASE2_DEX_RUNNER", "ts": int(time.time() * 1000)},
                "payload": payload,
            })
        if args.json:
            print(json.dumps({
                "mode": "settle_only" if args.settle_only else "observe_and_forecast",
                "compact_scorecard": compact_mode,
                "cycle": payload,
                "settlement": settlement,
                "scorecard": scorecard,
                "readiness": readiness,
                "dio_gate": dio_gate,
            }, indent=2, sort_keys=True, default=str))
        elif args.settle_only:
            print(
                f"SETTLEMENT_ONLY settled_now={settlement.get('settled', 0)} "
                f"forecasts={readiness.get('forecasts', 0)} "
                f"settled_non_abstain={readiness.get('settled_non_abstain_forecasts', 0)} "
                f"gate={dio_gate.get('decision')} orders=0"
            )
        else:
            run = payload.get("run") or {}
            print(
                f"{payload.get('status')} venue={run.get('venue')} run={run.get('run_id')} "
                f"symbols={run.get('symbols_evaluated', 0)} "
                f"forecasts={run.get('forecasts_total', 0)} "
                f"active={run.get('non_abstain_forecasts', 0)} "
                f"gate={dio_gate.get('decision')} orders=0"
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
            print(f"DEX Phase-2 cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
