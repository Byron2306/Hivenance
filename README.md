# Hivenance

A multi-agent crypto trading swarm that combines technical analysis strategies, on-chain DEX execution, centralised exchange (CEX) trading, regime detection, and a governance layer — all coordinated by a single `SwarmCoordinator`.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture overview](#architecture-overview)
- [Agent reference](#agent-reference)
- [BuzzService (staking & governance)](#buzzservice-staking--governance)
- [Trading strategies](#trading-strategies)
- [Risk management](#risk-management)
- [On-chain trading](#on-chain-trading)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration reference](#configuration-reference)
- [Quick start](#quick-start)
- [Desktop UI](#desktop-ui)
- [Docker deployment](#docker-deployment)
- [Project structure](#project-structure)
- [License](#license)

---

## What it does

Hivenance runs a continuous trading loop across multiple symbols. At each cycle it:

1. Fetches market data (price, volume, sentiment, tape trades) from CoinGecko, Kraken, and Binance.
2. Detects the current market regime (TREND_UP / TREND_DOWN / CHOP_RANGE / BREAKOUT / PANIC_VOLATILE / LOW_LIQUIDITY).
3. Runs parallel strategy workers (SMA crossover, RSI, Breakout, Momentum) and collects trade proposals.
4. Passes proposals through the `StrategyCouncil` for consensus and the `GovernanceQueen` for SVS scoring and position sizing.
5. Routes accepted orders through `SwarmGuard` (liquidity, spread, rate-limit checks) and the `KillSwitch` (equity floor / drawdown).
6. Executes trades on-chain via the 1inch API (Base L2 / Ethereum) or via CEX (Kraken / Binance).
7. Logs everything to SQLite via `DataStoreAgent` and broadcasts events to a lightweight `BuzzService` REST API that governs agent staking, rewards, and slashing.

All inter-agent decisions are staked using **Buzz tokens**, creating accountability for each agent's influence on real orders.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────┐
│                     SwarmCoordinator                     │
│  ┌───────────┐  ┌──────────┐  ┌─────────────────────┐  │
│  │MarketData │  │CoinGecko │  │  SentimentData /     │  │
│  │(Kraken)   │  │Data      │  │  TrendAnalysis       │  │
│  └───────────┘  └──────────┘  └─────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │               RegimeOracle (multi-TF)              │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │SMAWorker │  │RSIWorker │  │Breakout  │  │Momentum│  │
│  └──────────┘  └──────────┘  │Worker    │  │Worker  │  │
│                               └──────────┘  └────────┘  │
│                                                          │
│  ┌───────────────┐  ┌──────────────────────────────┐   │
│  │StrategyCouncil│  │      GovernanceQueen (SVS)    │   │
│  └───────────────┘  └──────────────────────────────┘   │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ SwarmGuard  │  │  KillSwitch  │  │  NurseAgent   │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
│                                                          │
│  ┌───────────────────┐   ┌──────────────────────────┐  │
│  │  KrakenTrader /   │   │  OpenClawAgent (1inch)   │  │
│  │  BinanceTrader    │   │  on-chain DEX execution  │  │
│  └───────────────────┘   └──────────────────────────┘  │
│                                                          │
│  ┌──────────┐  ┌────────────┐  ┌─────────────────────┐ │
│  │DataStore │  │Performance │  │ SecurityAgent       │ │
│  │Agent     │  │Agent       │  │                     │ │
│  └──────────┘  └────────────┘  └─────────────────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │            BuzzService (REST API)                │   │
│  │  lock · release · slash · credit · staking ledger│   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Agent reference

| Agent | File | Role |
|---|---|---|
| `SwarmCoordinator` | `agents/coordinator.py` | Orchestrates all agents; runs the main trading loop |
| `RegimeOracle` | `agents/oracle_regime.py` | Multi-timeframe market regime detection |
| `StrategyCouncil` | `agents/council.py` | Aggregates worker proposals; applies consensus weighting |
| `GovernanceQueen` | `agents/queen.py` | SVS scoring; position sizing; final BUY/SELL/HOLD decision |
| `SMAWorker` | `agents/strategy_workers.py` | SMA crossover proposals |
| `RSIWorker` | `agents/strategy_workers.py` | RSI overbought/oversold proposals |
| `BreakoutWorker` | `agents/strategy_workers.py` | Price breakout proposals |
| `MomentumWorker` | `agents/strategy_workers.py` | Momentum-based proposals |
| `SwarmGuard` | `agents/swarmguard.py` | Liquidity cap, spread/fee veto, rate limiting, risk rulebook |
| `KillSwitchAgent` | `agents/kill_switch.py` | Halts trading on equity floor or max drawdown breach |
| `NurseAgent` | `agents/nurse.py` | Periodic health checks; auto-restarts stale agents |
| `CoinSelector` | `agents/coin_selector.py` | Dynamic symbol selection by volume and spread |
| `MarketData` | `agents/market_data.py` | Kraken OHLCV + order book feeds |
| `WalletMonitor` | `agents/wallet_monitor.py` | On-chain wallet balance polling |
| `OpenClawAgent` | `agents/openclaw.py` | On-chain swap execution via 1inch API |
| `DataStoreAgent` | `agents/data_store_agent.py` | Persists candles, trades, events to SQLite |
| `PerformanceAgent` | `agents/performance_agent.py` | Tracks PnL, win-rate, execution quality |
| `SecurityAgent` | `agents/security_agent.py` | Monitors for anomalous activity; auto-pause support |
| `NetworkAgent` | `agents/network_agent.py` | P2P agent communication layer |
| `UIAgent` | `agents/ui_agent.py` | Flask web dashboard backend |
| `LoggingAnalyticsAgent` | `agents/logging_analytics.py` | Structured logging + analytics sink |

---

## BuzzService (staking & governance)

BuzzService is a lightweight FastAPI service (`buzzservice/`) that provides a staking ledger for agent accountability.

Each agent locks Buzz tokens before influencing a trade. If the trade is profitable the agent is credited; if it loses the agent is slashed. This creates a measurable cost for bad decisions.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/lock` | Lock tokens (pre-trade stake) |
| `POST` | `/release` | Release locked tokens |
| `POST` | `/slash` | Slash an agent's balance |
| `POST` | `/credit` | Credit an agent's balance |
| `GET` | `/balance/{account}` | Query current balance |

All requests are authenticated with HMAC-SHA256 via the `x-hive-sig` / `x-hive-service` headers. Set `BUZZ_SHARED_SECRET` to the same value in both the coordinator config and the BuzzService environment.

### Run BuzzService

```bash
uvicorn buzzservice.service:app --host 0.0.0.0 --port 9009
```

Or set `buzz_base_url` in `config/settings.yaml` and the coordinator starts expecting it automatically.

---

## Trading strategies

| Strategy | Trigger | Config keys |
|---|---|---|
| **SMA Crossover** | Fast SMA crosses above/below slow SMA | `sma_fast`, `sma_slow` |
| **RSI** | RSI crosses oversold/overbought threshold | `rsi_window`, `rsi_oversold`, `rsi_overbought` |
| **Breakout** | Close breaks above recent high / below recent low | `lookback` |
| **Momentum** | Directional price momentum over lookback window | `lookback` |

All strategies are proposal-only; the `StrategyCouncil` + `GovernanceQueen` make the final call. Set `strategy_type` in `settings.yaml` to use a single strategy instead of the full worker ensemble.

---

## Risk management

### SwarmGuard

Multi-layer trade filter applied before every order:

- **Liquidity cap** — order size is bounded by `liquidity_k × spread + liquidity_m`
- **Spread veto** — cancels orders when bid/ask spread exceeds `spread_guard_pct`
- **Fee buffer** — requires `expected_move_min_pct` to exceed estimated fees
- **Rate limiting** — at most `swarmguard_max_trades_per_hour` trades; minimum `swarmguard_min_trade_interval_sec` between trades
- **Consensus gate** — requires at least `swarmguard_consensus_min` agreeing agents
- **Configurable rulebook** — JSON risk rules loaded from `config/swarmguard_rules_v1.json`

### KillSwitch

Hard stop on any of:
- Portfolio equity drops below `killswitch_equity_floor_usd`
- Drawdown exceeds `max_drawdown_pct`
- `max_consecutive_losses` consecutive losing trades
- Daily loss exceeds `daily_loss_limit` USD

When triggered the coordinator halts all new orders and enters a grace period (`kill_switch_grace_sec`) before requiring manual reset.

### GovernanceQueen (SVS scoring)

The queen scores each proposal using a **Sovereign Validation Score (SVS)** that factors in:
- Regime alignment
- Execution quality history
- Historical performance metrics
- Strategy-specific confidence

Proposals below `svs_min_threshold` (default `0.35`) are rejected as HOLD.

---

## On-chain trading

Hivenance can route trades through the **1inch API** on Base L2 (chain ID 8453) or Ethereum mainnet.

Key settings:

| Setting | Description |
|---|---|
| `onchain_enabled` | Enable on-chain execution |
| `onchain_chain_id` | EVM chain ID (8453 = Base) |
| `onchain_slippage_bps` | Slippage tolerance in basis points |
| `onchain_max_gas_usd` | Abort if estimated gas cost exceeds this |
| `onchain_max_fee_eth` | Absolute max fee in ETH |
| `web3_rpc_url` | RPC endpoint (default: Base mainnet) |
| `watch_address` | Wallet address to monitor |
| `onchain_fallback_to_cex` | Fall back to Kraken/Binance if on-chain fails |

Token addresses for Base are pre-configured for ETH, XCN, TOSHI, WLD, and USDC in `settings.yaml` under `onchain_token_addresses`.

**Required env vars for on-chain:**
```
WEB3_PRIVATE_KEY=<your private key>
ONEINCH_API_KEY=<your 1inch API key>
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Tested on 3.10 and 3.14 |
| Redis | Used for pub/sub between agents (`redis_host`, `redis_port`) |
| Kraken account | API key + secret for CEX trading |
| Binance account | Optional; for Binance execution |
| 1inch API key | Required for on-chain execution |
| EVM wallet | Private key for on-chain signing |
| Ollama (optional) | Local LLM inference |

---

## Installation

```bash
git clone https://github.com/Byron2306/Hivenance.git
cd Hivenance
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy and edit the config:

```bash
cp config/settings.yaml config/settings.local.yaml
# Edit settings.local.yaml — set exchange keys, wallet address, etc.
```

Set secrets in your environment (do **not** commit these):

```bash
export KRAKEN_API_KEY=...
export KRAKEN_API_SECRET=...
export WEB3_PRIVATE_KEY=...
export ONEINCH_API_KEY=...
export BUZZ_SHARED_SECRET=...
```

---

## Configuration reference

All options live in `config/settings.yaml`. Key sections:

### Core trading

| Key | Default | Description |
|---|---|---|
| `exchange` | `kraken` | Primary CEX (`kraken` or `binance`) |
| `symbol` | `ETH/USD` | Primary trading pair |
| `multi_symbol_enabled` | `true` | Trade multiple symbols in parallel |
| `multi_symbols` | `[ETH/USD, XCN/USD, TOSHI/USD]` | Symbol list for multi-symbol mode |
| `interval` | `1m` | Candle interval |
| `lookback` | `500` | Candles to keep in memory |
| `poll_seconds` | `10` | Main loop interval (seconds) |
| `dry_run` | `false` | Paper-trade mode (no real orders) |

### Position sizing & risk

| Key | Default | Description |
|---|---|---|
| `risk_pct` | `0.005` | Fraction of free balance risked per trade |
| `max_trade_usd` | `0.5` | Maximum order size in USD |
| `min_trade_usd` | `0.1` | Minimum order size in USD |
| `max_notional` | `2.0` | Max total notional exposure in USD |
| `max_drawdown_pct` | `10.0` | Kill-switch drawdown threshold (%) |
| `daily_loss_limit` | `50.0` | Daily loss limit in USD |
| `max_consecutive_losses` | `5` | Kill-switch consecutive loss threshold |
| `killswitch_equity_floor_usd` | `25.0` | Minimum equity before halt |

### Coin selection (auto-switching)

| Key | Default | Description |
|---|---|---|
| `coin_selection_enabled` | `true` | Enable dynamic coin selection |
| `coin_selection_interval_sec` | `600` | Re-evaluate interval |
| `coin_selection_top_n` | `3` | Number of symbols to trade |
| `coin_selection_min_vol_usd` | `100000` | Minimum 24h volume filter |
| `coin_selection_spread_max` | `0.03` | Maximum acceptable spread |

### BuzzService

| Key | Default | Description |
|---|---|---|
| `buzz_base_url` | `http://localhost:9009` | BuzzService endpoint |
| `buzz_shared_secret` | `CHANGE_ME` | HMAC secret — **change before deploying** |
| `buzz_account` | `hivenance-system` | Coordinator account name |
| `buzz_bootstrap_amount` | `250` | Initial token balance seeded on startup |
| `buzz_cycle_length_sec` | `120` | Governance cycle duration |
| `buzz_stake_queen` | `20` | Tokens staked per queen decision |
| `buzz_stake_council` | `10` | Tokens staked per council consensus |
| `buzz_stake_worker_default` | `8` | Default stake per strategy worker |

---

## Quick start

### 1. Start Redis

```bash
redis-server
```

### 2. Start BuzzService

```bash
uvicorn buzzservice.service:app --host 0.0.0.0 --port 9009
```

### 3. Run in dry-run mode first

```bash
python main.py --config config/settings.yaml
```

Set `dry_run: true` in your config to paper-trade with no real orders until you're satisfied with behaviour.

### 4. Enable the web UI

Set `ui_enabled: true` in `settings.yaml`, then open `http://localhost:5000` while the coordinator is running.

---

## Desktop UI

The Flask-based web dashboard runs on port `5000` (configurable via `ui_port`).

Features:
- Live agent status and health
- Open positions and recent trades
- PnL curve and win-rate metrics
- SwarmGuard veto log
- Kill-switch status
- BuzzService staking ledger

Run standalone (without the full coordinator):

```bash
python run_ui_server.py
```

---

## Docker deployment

A `Dockerfile` is provided in `docker/`. It packages the coordinator and all dependencies:

```bash
# Build
docker build -f docker/Dockerfile -t hivenance .

# Run (pass secrets as env vars, never bake them into the image)
docker run -d \
  -e KRAKEN_API_KEY=... \
  -e KRAKEN_API_SECRET=... \
  -e WEB3_PRIVATE_KEY=... \
  -e BUZZ_SHARED_SECRET=... \
  -p 5000:5000 \
  hivenance
```

For production, run BuzzService and Redis as separate containers and connect them via a Docker network.

---

## Project structure

```
Hivenance/
├── agents/
│   ├── coordinator.py          # SwarmCoordinator — main orchestration loop
│   ├── queen.py                # GovernanceQueen (SVS scoring)
│   ├── council.py              # StrategyCouncil (consensus)
│   ├── strategy_workers.py     # SMA / RSI / Breakout / Momentum workers
│   ├── strategy.py             # Core indicator functions (SMA, EMA, RSI, MACD)
│   ├── oracle_regime.py        # Multi-TF regime detection
│   ├── swarmguard.py           # Pre-trade risk filter
│   ├── kill_switch.py          # Hard stop / equity floor
│   ├── nurse.py                # Agent health monitor
│   ├── execution.py            # BinanceTrader / KrakenTrader
│   ├── openclaw.py             # On-chain 1inch execution
│   ├── market_data.py          # Market data feeds
│   ├── wallet_monitor.py       # On-chain wallet balance
│   ├── coin_selector.py        # Dynamic symbol selection
│   ├── data_store_agent.py     # SQLite persistence
│   ├── performance_agent.py    # PnL + execution quality tracking
│   ├── security_agent.py       # Anomaly detection
│   ├── network_agent.py        # P2P agent bus
│   ├── ui_agent.py             # Flask dashboard backend
│   ├── user_interface.py       # UI helpers
│   ├── tracing.py              # OpenTelemetry tracing setup
│   └── logging_analytics.py   # Structured logging
├── buzzservice/
│   ├── service.py              # FastAPI staking service
│   ├── db.py                   # SQLite ledger
│   ├── auth.py                 # HMAC verification
│   └── client.py               # BuzzServiceClient (used by agents)
├── config/
│   ├── settings.yaml           # Main configuration
│   ├── swarmguard_rules_v1.json
│   ├── risk_register.json
│   └── risk_agent_control_map.json
├── data/
│   └── swarm_data.db           # SQLite database (runtime)
├── docker/
│   └── Dockerfile
├── logs/                       # Runtime log files
├── static/                     # Static files for web UI
├── main.py                     # Entry point
├── run_ui_server.py            # Standalone UI launcher
├── requirements.txt
└── SwarmOS.txt                 # Regime detection agent spec
```

---

## License

This project is proprietary. All rights reserved.
