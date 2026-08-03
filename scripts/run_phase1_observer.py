#!/usr/bin/env python3
"""Run the Phoenix Phase-1 Observation Swarm without loading execution modules.

This process uses public CCXT market-data endpoints only. It persists immutable
observation runs and symbol snapshots to the configured SQLite database. It has
no order submission, wallet, or authenticated exchange path.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent

ALLOWED_PUBLIC_VENUES = {"kraken", "coinbase", "binance", "valr", "luno"}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_observer_config(settings_path: Path, profile_path: Path | None = None) -> SimpleNamespace:
    settings = _load_yaml(settings_path)
    resolved_profile = profile_path
    if resolved_profile is None:
        configured = settings.get("profile_path")
        if configured:
            candidate = Path(str(configured))
            resolved_profile = candidate if candidate.is_absolute() else ROOT / candidate
    if resolved_profile:
        settings.update(_load_yaml(resolved_profile))

    required_safety = {
        "phase0_quarantine": True,
        "dry_run": True,
        "live_mode": False,
        "auto_trade_enabled": False,
        "onchain_enabled": False,
        "coin_selection_auto_switch": False,
        "public_bot_metrics_auto_promote": False,
        "swarmguard_small_trade_bypass": False,
    }
    violations = [
        f"{key}={settings.get(key)!r} expected {expected!r}"
        for key, expected in required_safety.items()
        if settings.get(key) is not expected
    ]
    if int(settings.get("hummingbot_v2_leverage", 1)) != 1:
        violations.append("hummingbot_v2_leverage must equal 1")
    if not bool(settings.get("phase1_observation_enabled", True)):
        violations.append("phase1_observation_enabled must be true")
    if violations:
        raise RuntimeError("Phase-1 safety preflight failed: " + "; ".join(violations))
    return SimpleNamespace(**settings)


def build_public_client(exchange_id: str) -> Any:
    exchange_id = exchange_id.lower().strip()
    if exchange_id not in ALLOWED_PUBLIC_VENUES:
        raise ValueError(f"Unsupported Phase-1 public venue: {exchange_id}")
    try:
        import ccxt
    except ImportError as exc:
        raise RuntimeError(
            "CCXT is required for the standalone observer. Install requirements-phase1.txt"
        ) from exc
    factory = getattr(ccxt, exchange_id, None)
    if factory is None:
        raise RuntimeError(f"Installed CCXT build does not expose venue {exchange_id}")
    return factory({"enableRateLimit": True, "timeout": 20_000})


class StoreBridge:
    def __init__(self, store: DataStoreAgent) -> None:
        self.store = store

    def share_data(self, _key: str, event: dict[str, Any]) -> None:
        self.store.handle_event(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hivenance Phoenix Phase-1 public observation swarm")
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--exchange", choices=sorted(ALLOWED_PUBLIC_VENUES))
    parser.add_argument("--database", type=Path)
    parser.add_argument("--once", action="store_true", help="Collect one cycle and exit")
    parser.add_argument("--json", action="store_true", help="Print the complete cycle payload")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    if args.exchange:
        cfg.exchange = args.exchange
    exchange_id = str(getattr(cfg, "exchange", "kraken") or "kraken").lower()
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/hivenance.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    client = build_public_client(exchange_id)
    store = DataStoreAgent(str(db_path))
    observer = ObservationSwarmAgent(cfg, client, coordinator=StoreBridge(store))

    def collect() -> None:
        payload = observer.run_once()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            run = payload.get("run") or {}
            print(
                f"{payload.get('status')} run={run.get('run_id')} "
                f"observed={run.get('symbols_successful', 0)}/{run.get('symbols_attempted', 0)} "
                f"eligible={run.get('symbols_eligible', 0)} "
                f"quality={float(run.get('mean_data_quality') or 0):.3f} "
                "orders=0"
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
    interval = max(30, int(getattr(cfg, "phase1_observation_interval_sec", 120) or 120))
    while not stopping:
        started = time.monotonic()
        try:
            collect()
        except Exception as exc:
            print(f"Observation cycle failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        remaining = max(1.0, interval - (time.monotonic() - started))
        deadline = time.monotonic() + remaining
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
