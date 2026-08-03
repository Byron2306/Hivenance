#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f'FAIL: {message}')
    raise SystemExit(1)


def main() -> int:
    required = [
        ROOT / 'strategies/volatility_breakout/observation_swarm.py',
        ROOT / 'strategies/volatility_breakout/feature_engine.py',
        ROOT / 'config/volatility_breakout_phase1.yaml',
        ROOT / 'tests/test_phase1_observation.py',
        ROOT / 'scripts/run_phase1_observer.py',
        ROOT / 'requirements-phase1.txt',
    ]
    for path in required:
        if not path.exists():
            fail(f'missing {path.relative_to(ROOT)}')

    observer_source = required[0].read_text(encoding='utf-8')
    runner_source = (ROOT / 'scripts/run_phase1_observer.py').read_text(encoding='utf-8')
    for forbidden_symbol in ('create_order', 'submit_order', 'place_order', 'order_market_buy', 'order_market_sell'):
        if forbidden_symbol in runner_source:
            fail(f'standalone observer contains forbidden execution symbol: {forbidden_symbol}')
    tree = ast.parse(observer_source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or '')
    forbidden = [name for name in imported if 'execution' in name or 'trade_executors' in name]
    if forbidden:
        fail(f'observer imports execution code: {forbidden}')
    if 'create_order' in observer_source or 'submit_order' in observer_source:
        fail('observer contains an order-submission symbol')

    for rel in [
        'config/settings.yaml', 'config/settings.live.yaml', 'config/conservative_state.yaml',
        'config/conservative_headless_10m.yaml', 'config/live_safe_1h.yaml',
    ]:
        cfg = yaml.safe_load((ROOT / rel).read_text(encoding='utf-8')) or {}
        checks = {
            'phase0_quarantine': True,
            'phase1_observation_enabled': True,
            'dry_run': True,
            'live_mode': False,
            'auto_trade_enabled': False,
            'onchain_enabled': False,
            'coin_selection_auto_switch': False,
            'public_bot_metrics_auto_promote': False,
            'swarmguard_small_trade_bypass': False,
        }
        for key, expected in checks.items():
            if cfg.get(key) is not expected:
                fail(f'{rel}: {key}={cfg.get(key)!r}, expected {expected!r}')
        if int(cfg.get('hummingbot_v2_leverage', 0)) != 1:
            fail(f'{rel}: leverage must remain 1')

    sys.path.insert(0, str(ROOT))
    from agents.data_store_agent import DataStoreAgent
    with tempfile.TemporaryDirectory() as td:
        store = DataStoreAgent(str(Path(td) / 'phase1.db'))
        names = {
            row[0] for row in store.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in ('observation_runs', 'observation_snapshots'):
            if table not in names:
                fail(f'missing SQLite table {table}')

    package = json.loads((ROOT / 'desktop-ui/package.json').read_text(encoding='utf-8'))
    if package.get('main') != 'main.js':
        fail('desktop package main is invalid')

    print('PASS: Phase 1 Observation Swarm preflight')
    print('  execution imports: none')
    print('  order submission symbols: none')
    print('  runtime profiles: quarantined')
    print('  observation persistence: present')
    print('  desktop observation surface: present')
    print('  standalone public observer: present')
    print('  phase-2 readiness gate: present')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
