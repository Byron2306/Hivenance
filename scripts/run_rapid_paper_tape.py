#!/usr/bin/env python3
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
from scripts.run_phase1_observer import build_public_client, load_observer_config
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent
from strategies.volatility_breakout.rapid_paper_tape import LocalLLMHypothesisCritic, RapidPaperTape


class StoreBridge:
    def __init__(self, store: DataStoreAgent) -> None:
        self.store = store

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def apply_loose_research_profile(cfg: Any) -> dict[str, Any]:
    """Loosen only research/paper thresholds for rapid evidence gathering."""
    overrides = {
        "phase2_minimum_edge_multiple": 0.75,
        "phase2_federation_minimum_edge_multiple": 0.75,
        "phase2_breakout_min_expansion": 1.05,
        "phase2_breakout_min_volume_zscore": 0.0,
        "phase2_breakout_min_return_zscore": 0.25,
        "phase2_reversion_min_stretch_zscore": 0.8,
        "phase2_reversion_min_range_extreme": 0.65,
        "phase2_rapid_paper_min_expected_net_bps": -5.0,
        "phase2_rapid_paper_min_probability": 0.45,
    }
    applied = {}
    for key, value in overrides.items():
        old = getattr(cfg, key, None)
        setattr(cfg, key, value)
        applied[key] = {"from": old, "to": value}
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a fast public-data paper tape from Phase-2 hypotheses. No private exchange calls."
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--duration-sec", type=int, default=900)
    parser.add_argument("--interval-sec", type=int, default=30)
    parser.add_argument("--open-limit", type=int, default=25)
    parser.add_argument("--settlement-tolerance-sec", type=float, default=900.0)
    parser.add_argument("--settlement-limit", type=int, default=500)
    parser.add_argument("--skip-settlement", action="store_true", help="open fresh paper trades without sweeping old outcomes")
    parser.add_argument("--fresh-window-sec", type=int)
    parser.add_argument("--directions", default=None, help="comma-separated forecast directions for paper opens; default config is UP")
    parser.add_argument("--loose", action="store_true", help="loosen research/paper thresholds in this process only")
    parser.add_argument("--champion-scout", action="store_true", help="admit only fresh paper forecasts backed by positive settled slice evidence")
    parser.add_argument("--database-only", action="store_true", help="use already persisted forecasts/observations only")
    parser.add_argument("--llm", action="store_true", help="ask local Ollama to critique paper entries")
    parser.add_argument("--llm-veto", action="store_true", help="allow Ollama critique to veto paper entries")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-model", default="beast-crystal-qwen25-05b:latest")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    if args.exchange:
        cfg.exchange = args.exchange
    cfg.phase2_hypotheses_enabled = True
    cfg.phase2_rapid_paper_notional_usd = float(getattr(cfg, "phase2_rapid_paper_notional_usd", 5.0) or 5.0)
    cfg.phase2_rapid_paper_max_open_trades = int(getattr(cfg, "phase2_rapid_paper_max_open_trades", 12) or 12)
    if args.fresh_window_sec is not None:
        cfg.phase2_rapid_paper_max_forecast_age_sec = max(10, int(args.fresh_window_sec))
    if args.directions:
        cfg.phase2_rapid_paper_allowed_directions = [
            item.strip().upper() for item in str(args.directions).split(",") if item.strip()
        ]
    if args.champion_scout:
        cfg.phase2_rapid_paper_champion_scout_enabled = True
    loose_overrides = apply_loose_research_profile(cfg) if args.loose else {}

    exchange_id = str(getattr(cfg, "exchange", "kraken") or "kraken").lower()
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = DataStoreAgent(str(db_path))
    bridge = StoreBridge(store)
    swarm = None
    if not args.database_only:
        client = build_public_client(exchange_id)
        observer = ObservationSwarmAgent(cfg, client, coordinator=bridge)
        swarm = HypothesisSwarmAgent(cfg, observer, coordinator=bridge)
    critic = LocalLLMHypothesisCritic(
        enabled=args.llm,
        ollama_url=args.ollama_url,
        model=args.ollama_model,
        hard_veto=args.llm_veto,
    )
    tape = RapidPaperTape(cfg, store, critic=critic)

    started = time.monotonic()
    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    cycles = 0
    last_payload = {}

    def emit(message: str) -> None:
        if not args.json:
            print(message, flush=True)

    while not stopping:
        cycle_started = time.monotonic()
        cycles += 1
        emit(f"RAPID_TAPE cycle={cycles} stage=phase2 mode={'database_only' if args.database_only else exchange_id}")
        phase2 = swarm.run_once() if swarm is not None else None
        emit(f"RAPID_TAPE cycle={cycles} stage=settlement")
        if args.skip_settlement:
            settlement = {"examined": 0, "settled": 0, "pending": 0, "skipped": True}
            closed = {"closed": 0, "examined": 0, "skipped": True}
        else:
            settlement = store.settle_mature_hypothesis_forecasts(
                tolerance_sec=float(args.settlement_tolerance_sec),
                limit=max(1, int(args.settlement_limit)),
            )
            emit(f"RAPID_TAPE cycle={cycles} stage=close_settled")
            closed = tape.close_settled()
        emit(f"RAPID_TAPE cycle={cycles} stage=direct_rapid_settlement")
        direct_closed = tape.settle_due_open_trades(tolerance_sec=float(args.settlement_tolerance_sec))
        expired = tape.expire_stale_open_trades(tolerance_sec=float(args.settlement_tolerance_sec))
        negative_crystals = tape.backfill_negative_crystals()
        emit(f"RAPID_TAPE cycle={cycles} stage=open_recent")
        opened = tape.open_from_recent_forecasts(limit=args.open_limit)
        payload = {
            "phase": "rapid_paper_tape",
            "phase2": phase2,
            "settlement": settlement,
            "closed": closed,
            "direct_closed": direct_closed,
            "expired": expired,
            "negative_crystals": negative_crystals,
            "opened": opened,
            "scorecard": tape.scorecard(limit=20),
        }
        payload["cycle"] = cycles
        payload["elapsed_sec"] = round(time.monotonic() - started, 3)
        payload["duration_sec"] = 0 if args.once else int(args.duration_sec)
        payload["loose_research_profile"] = bool(args.loose)
        payload["loose_overrides"] = loose_overrides
        payload["llm_enabled"] = bool(args.llm)
        payload["llm_veto_enabled"] = bool(args.llm_veto)
        payload["champion_scout_enabled"] = bool(getattr(cfg, "phase2_rapid_paper_champion_scout_enabled", False))
        payload["allowed_directions"] = list(getattr(cfg, "phase2_rapid_paper_allowed_directions", ["UP"]) or ["UP"])
        last_payload = payload
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            score = payload.get("scorecard") or {}
            opened = payload.get("opened") or {}
            closed = payload.get("closed") or {}
            direct_closed = payload.get("direct_closed") or {}
            expired = payload.get("expired") or {}
            negative_crystals = payload.get("negative_crystals") or {}
            settlement = payload.get("settlement") or {}
            print(
                f"RAPID_TAPE cycle={cycles} opened={opened.get('opened', 0)} "
                f"skip_dup={opened.get('skipped_duplicate_open', 0)} "
                f"skip_loss={opened.get('skipped_recent_loss', 0)} "
                f"skip_crystal={opened.get('skipped_negative_memory', 0)} "
                f"skip_probation={opened.get('skipped_model_direction_probation', 0)} "
                f"skip_scout={opened.get('skipped_champion_scout', 0)} "
                f"skip_gap={opened.get('skipped_data_gap', 0)} "
                f"closed={closed.get('closed', 0)} direct_closed={direct_closed.get('closed', 0)} "
                f"expired={expired.get('expired', 0)} "
                f"neg_crystals={negative_crystals.get('created_or_updated', 0)} "
                f"settled={settlement.get('settled', 0)} "
                f"open={score.get('open', 0)} tape_closed={score.get('closed', 0)} "
                f"win_rate={float(score.get('win_rate', 0.0)):.2%} "
                f"total_net_bps={float(score.get('total_net_bps', 0.0)):.2f} "
                "private_orders=0"
            )
        if args.once:
            break
        if (time.monotonic() - started) >= max(1, int(args.duration_sec)):
            break
        sleep_for = max(1.0, int(args.interval_sec) - (time.monotonic() - cycle_started))
        deadline = time.monotonic() + sleep_for
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))

    final = tape.scorecard(limit=25)
    if args.json:
        print(json.dumps({"final": final, "last_cycle": last_payload}, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"FINAL_RAPID_TAPE cycles={cycles} open={final.get('open', 0)} "
            f"closed={final.get('closed', 0)} wins={final.get('wins', 0)} losses={final.get('losses', 0)} "
            f"win_rate={float(final.get('win_rate', 0.0)):.2%} "
            f"mean_net_bps={float(final.get('mean_net_bps', 0.0)):.2f} "
            f"total_net_bps={float(final.get('total_net_bps', 0.0)):.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
