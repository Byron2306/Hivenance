# Hivenance Phoenix Phase 1: Observation Swarm operator guide

## Purpose

Phase 1 watches public spot markets, ranks candidates for research observation, and stores durable evidence. It does not authenticate to an exchange, inspect wallets, create order intents, or submit orders.

The safety invariants are:

- `phase0_quarantine: true`
- `dry_run: true`
- `live_mode: false`
- `auto_trade_enabled: false`
- `onchain_enabled: false`
- `coin_selection_auto_switch: false`
- `public_bot_metrics_auto_promote: false`
- `swarmguard_small_trade_bypass: false`
- `hummingbot_v2_leverage: 1`
- observation candidates always have `execution_eligible: false`
- observation runs always record `execution_wired: false` and `orders_submitted: 0`

## Minimal public-only launch

From the package root:

```bash
python3 -m venv .venv-phase1
source .venv-phase1/bin/activate
python -m pip install -r requirements-phase1.txt
python scripts/phase0_preflight.py
python scripts/phase1_preflight.py
python scripts/run_phase1_observer.py --once
```

For continuous observation:

```bash
python scripts/run_phase1_observer.py
```

To print the full evidence payload:

```bash
python scripts/run_phase1_observer.py --once --json
```

To select an explicitly supported public venue:

```bash
python scripts/run_phase1_observer.py --exchange kraken --once
```

Supported public-observation IDs are `kraken`, `coinbase`, `binance`, `valr`, and `luno`, subject to the capabilities exposed by the installed CCXT version and the venue's public API.

## What one cycle records

Each run stores:

- deterministic dataset hash
- venue and UTC timestamps
- attempted and successful symbol counts
- mean data quality
- candle freshness and continuity
- 24-hour quote volume
- L2 spread in basis points
- executable depth inside the configured 25-basis-point band
- short and baseline realised volatility
- volatility-expansion ratio
- volume z-score
- book-imbalance proxy
- explicit unavailable states for true order-flow imbalance and trade-count history
- candidate score, eligibility, and rejection reasons

SQLite projections are stored in:

- `observation_runs`
- `observation_snapshots`

The default database path comes from `db_path` in the active configuration.

## Main configuration controls

```yaml
phoenix_phase: 1
phase1_observation_enabled: true
phase1_observation_interval_sec: 120
phase1_observation_max_symbols: 12
phase1_observation_quote_assets: [USD, USDT, USDC]
phase1_observation_timeframe: 1m
phase1_observation_lookback: 121
phase1_observation_orderbook_depth: 50
phase1_observation_short_window: 5
phase1_observation_baseline_window: 60
phase1_observation_stale_after_sec: 180
phase1_observation_min_success_ratio: 0.90
phase1_observation_min_quote_volume_usd: 5000000
phase1_observation_min_depth_usd_25bps: 25000
phase1_observation_max_spread_bps: 35
phase1_observation_min_data_quality: 0.99
```

## Phase 2 review gate

Phase 1 cannot unlock execution. It can only become ready for a human Phase 2 review.

The readiness projection requires:

- at least seven distinct UTC observation days
- mean data quality at or above the configured gate
- healthy-run ratio at or above the configured gate
- one or more persisted snapshots
- zero execution-wired violations
- zero submitted orders

The gate reports `ready_for_phase2_review`; `execution_eligible` remains false.

## Desktop view

The Electron console now includes **Observation**. It displays:

- current swarm health
- symbols observed
- mean data quality
- distinct evidence days
- run identifier and dataset hash
- ranked candidates and rejection reasons
- permanent zero-order safety status

## Known Phase 1 boundaries

- Data collection is REST-polled, not yet WebSocket event-sourced.
- True order-flow imbalance requires sequential trades or order-book deltas and remains unavailable.
- Trade-count z-scores remain unavailable until trade-count history is captured.
- Listing timestamps are not consistently supplied by CCXT venues; unknown listing age is preserved rather than invented.
- Venue count is currently one per observer process. Cross-venue confirmation belongs to the next research layer.
- No profitability claim is made. Phase 1 creates trustworthy observations, not trades.
