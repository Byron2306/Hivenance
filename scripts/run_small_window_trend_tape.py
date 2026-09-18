#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.rapid_paper_tape import RapidPaperTape


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Open paper-only trades from observed small-window trend comparisons."
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--window-sec", type=int)
    parser.add_argument(
        "--windows-sec",
        help="comma-separated comparison windows; defaults to profile phase2_small_window_trend_windows_sec",
    )
    parser.add_argument("--hold-sec", type=int)
    parser.add_argument("--max-age-sec", type=int)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--settlement-tolerance-sec", type=float)
    parser.add_argument("--repeat-min-samples", type=int)
    parser.add_argument("--repeat-min-win-rate", type=float)
    parser.add_argument("--repeat-min-mean-net-bps", type=float)
    parser.add_argument("--repeat-min-total-net-bps", type=float)
    parser.add_argument(
        "--raise-open-cap",
        type=int,
        default=0,
        help="temporarily raise this process's paper open capacity by N slots.",
    )
    parser.add_argument("--settle-first", action="store_true")
    parser.add_argument("--expire-first", action="store_true")
    parser.add_argument("--duration-sec", type=int, default=0)
    parser.add_argument("--interval-sec", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    store = DataStoreAgent(str(db_path))
    tape = RapidPaperTape(cfg, store)
    active_before = tape.active_count()
    if args.raise_open_cap > 0:
        tape.max_open = max(tape.max_open, active_before + int(args.raise_open_cap))

    preflight: dict[str, Any] = {
        "active_before": active_before,
        "max_open": tape.max_open,
        "max_open_per_symbol": tape.max_open_per_symbol,
        "authority": "paper_only_no_private_exchange",
    }
    if args.settle_first:
        preflight["direct_closed"] = tape.settle_due_open_trades(tolerance_sec=900.0)
    if args.expire_first:
        preflight["expired"] = tape.expire_stale_open_trades(tolerance_sec=900.0)

    started = time.monotonic()
    cycle = 0
    last_payload: dict[str, Any] = {}
    while True:
        cycle += 1
        tolerance_sec = float(
            args.settlement_tolerance_sec
            if args.settlement_tolerance_sec is not None
            else getattr(cfg, "phase2_small_window_trend_settlement_tolerance_sec", 180.0)
        )
        direct_closed = tape.settle_due_open_trades(tolerance_sec=tolerance_sec)
        expired = tape.expire_stale_open_trades(tolerance_sec=tolerance_sec)
        if args.windows_sec:
            windows_sec = tuple(
                int(float(item.strip()))
                for item in str(args.windows_sec).split(",")
                if item.strip()
            )
        else:
            configured_windows = getattr(cfg, "phase2_small_window_trend_windows_sec", None)
            if configured_windows:
                windows_sec = tuple(int(float(item)) for item in configured_windows)
            elif args.window_sec:
                windows_sec = (max(30, int(args.window_sec)),)
            else:
                windows_sec = None
        opened = tape.open_from_trend_comparisons(
            limit=max(1, int(args.limit or 1)),
            window_sec=max(30, int(args.window_sec or getattr(cfg, "phase2_small_window_trend_window_sec", 900) or 900)),
            windows_sec=windows_sec,
            hold_sec=max(30, int(args.hold_sec or getattr(cfg, "phase2_small_window_trend_hold_sec", 300) or 300)),
            max_age_sec=max(30, int(args.max_age_sec or getattr(cfg, "phase2_small_window_trend_max_age_sec", 1800) or 1800)),
        )
        repeatability = tape.repeatable_mover_scorecard(
            min_samples=int(
                args.repeat_min_samples
                if args.repeat_min_samples is not None
                else getattr(cfg, "phase2_small_window_repeat_min_samples", 3)
            ),
            min_win_rate=float(
                args.repeat_min_win_rate
                if args.repeat_min_win_rate is not None
                else getattr(cfg, "phase2_small_window_repeat_min_win_rate", 0.55)
            ),
            min_mean_net_bps=float(
                args.repeat_min_mean_net_bps
                if args.repeat_min_mean_net_bps is not None
                else getattr(cfg, "phase2_small_window_repeat_min_mean_net_bps", 5.0)
            ),
            min_total_net_bps=float(
                args.repeat_min_total_net_bps
                if args.repeat_min_total_net_bps is not None
                else getattr(cfg, "phase2_small_window_repeat_min_total_net_bps", 10.0)
            ),
            limit=25,
        )
        payload = {
            "schema": "small_window_trend_tape_run_v1",
            "cycle": cycle,
            "preflight": preflight,
            "direct_closed": direct_closed,
            "expired": expired,
            "opened": opened,
            "repeatability": repeatability,
            "scorecard": tape.scorecard(limit=12),
        }
        last_payload = payload
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str), flush=True)
        else:
            print(
                f"TREND_TAPE cycle={cycle} opened={opened.get('opened', 0)} examined={opened.get('examined', 0)} "
                f"direct_closed={direct_closed.get('closed', 0)} expired={expired.get('expired', 0)} "
                f"repeatable={len(repeatability.get('promoted') or [])} "
                f"skipped={opened.get('skipped', 0)} cap={opened.get('skipped_capacity', 0)} "
                f"symbol_cap={opened.get('skipped_symbol_cap', 0)} private_orders=0",
                flush=True,
            )
            for row in opened.get("opened_candidates") or []:
                print(
                        "OPENED "
                        f"{row.get('symbol')} {row.get('direction')} {row.get('window_label') or row.get('window_sec')} "
                        f"move_bps={float(row.get('comparison_return_bps') or 0.0):.2f} "
                        f"net_bps={float(row.get('expected_net_bps') or 0.0):.2f} "
                        f"spread_bps={float(row.get('spread_bps') or 0.0):.2f} "
                        f"health={float(row.get('health_score') or 0.0):.2f}",
                    flush=True,
                )
            if not opened.get("opened_candidates"):
                for row in opened.get("candidates") or []:
                    print(
                        "CANDIDATE "
                        f"{row.get('symbol')} {row.get('direction')} {row.get('window_label') or row.get('window_sec')} "
                        f"move_bps={float(row.get('comparison_return_bps') or 0.0):.2f} "
                        f"net_bps={float(row.get('expected_net_bps') or 0.0):.2f} "
                        f"spread_bps={float(row.get('spread_bps') or 0.0):.2f} "
                        f"health={float(row.get('health_score') or 0.0):.2f}",
                        flush=True,
                    )
        if int(args.duration_sec or 0) <= 0:
            break
        if time.monotonic() - started >= int(args.duration_sec):
            break
        time.sleep(max(1, int(args.interval_sec or 60)))
    if args.json and int(args.duration_sec or 0) > 0:
        print(json.dumps({"final": last_payload}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
