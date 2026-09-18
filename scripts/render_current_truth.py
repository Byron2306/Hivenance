#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.current_truth import build_current_truth, format_current_truth


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Phoenix's authoritative truth directly from SQLite evidence")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "CURRENT_TRUTH.json")
    parser.add_argument("--exact", action="store_true", help="recompute full-history gate inputs instead of fast compact truth")
    parser.add_argument("--compact-limit", type=int, default=20000)
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = DataStoreAgent(str(db_path))
    report = build_current_truth(store, cfg, db_path, exact=args.exact, compact_limit=args.compact_limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(format_current_truth(report))
        print(f"Saved: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
