# Public Bot Adaptation Layers

Hivenance uses public trading bots as reference systems and sidecars. The goal is to borrow mature patterns without handing wallet authority or core risk control to external code.

## Hummingbot Strategy V2

Use Hummingbot Strategy V2 as the model for executor lifecycle.

- `position_executor`: best fit for Hivenance directional `BUY`/`SELL` proposals.
- `twap_executor`: safer entries and exits when one-shot fills are too aggressive.
- `grid_executor` and `dca_executor`: range and mean-reversion execution styles.
- `executor_orchestrator.py`: reference for create/monitor/stop executor lifecycle.
- `controllers/directional_trading`: `macd_bb_v1`, `bollinger_v2`, and `supertrend_v1` are candidates for local workers.
- `controllers/market_making`: `pmm_simple` and `pmm_dynamic` should start as watch-only liquidity and quote-quality advisors.

Current Hivenance layer:

- `agents/hummingbot_strategy_v2.py` catalogs these files without importing Hummingbot.
- `agents/trade_executors.py` exposes `hummingbot_v2` in plan-only mode.
- `/public_bots.json` includes the Strategy V2 executor/controller inventory.
- `/hummingbot/plan.json` builds local executor plans from Hivenance intents.
- `/hummingbot/lifecycle.json` controls persisted create/monitor/stop/retry/close lifecycle state.
- `/integration_planes.json` and `/integrations` expose the current adapter, worker, executor, and protection planes.
- `scripts/hummingbot_sidecar_runner.py` is the production runner template target for `hummingbot_sidecar_command`.

Current adapter layer:

- `HummingbotV2IntentAdapter` creates plan-only config dictionaries for `position`, `twap`, `grid`, `dca`, `xemm`, and `arbitrage`.
- `hummingbot_v2.plan(executor_type, intent)` returns the translated config plus source executor metadata.
- Live sidecar execution remains disabled by default. It only starts an external command when `hummingbot_sidecar_live_enabled` and `hummingbot_sidecar_command` are explicitly configured.

## Freqtrade

Use Freqtrade as a clean-room reference for protections and pairlists.

- Protections: cooldown, stoploss guard, max drawdown, low-profit pair rules.
- Pairlists: volume, spread, volatility, and age filters.

Best Hivenance targets:

- SwarmGuard rules for cooldown and drawdown protections.
- DataStore/pair protection tables for per-pair state.
- Coin promotion and symbol selection filters.

Current clean-room layer:

- `agents/pair_protections.py` evaluates cooldown, stoploss-guard-style bad exits, max daily loss, max drawdown, low-profit quarantine, failed quotes, and route-loss spikes.
- The same evaluator applies pairlist-style volume, spread, volatility, and age filters.
- Coordinator persists results through `DataStoreAgent.upsert_pair_protection`.
- SwarmGuard reads persisted pair protection state and vetoes protected symbols during live decision evaluation.

Freqtrade is GPL-licensed, so Hivenance should not import its internals.

## Public Bot Backtesting

Use public bot systems as sidecar research engines.

- `agents/public_bot_backtesting.py` exports candles and worker proposals into `data/public_bot_backtests/<run_id>`.
- `/public_bot/backtest/export.json` creates sidecar input artifacts for Freqtrade, Jesse, or generic replay engines.
- `/public_bot/backtest/ingest.json` stores returned metrics in SQLite for later worker weighting.
- Ingested metrics are applied to durable worker performance stats and symbol promotion evidence.

## Jesse

Use Jesse's MIT examples for new local strategy workers.

- `Donchian`
- `TurtleRules`
- `KDJstrategy`
- `MACD_EMA`
- `SimpleBollinger`

These can be ported cleanly into `agents/strategy_workers.py` because the examples are small strategy patterns.

## Market-Making Advisors

Use Hummingbot PMM controllers as watch-only quote-quality models first.

- `agents/market_making_advisors.py` implements `pmm_simple` and `pmm_dynamic` style advisors.
- Advisors score liquidity, roundtrip/spread, volume, and volatility.
- Advisors emit watch-only bid/ask quote plans when a current price is available.
- Pair protection payloads include `quote_advice`, and `/quote_advice.json` exposes the advisor plane.

## OctoBot

Use OctoBot as a reference for automation structure.

- Event/condition/action automation is useful for operator workflows.
- Strategy/profile ideas can inform future UI and automation rules.

OctoBot is GPL-licensed, so keep it sidecar/reference only.

## Implementation Order

1. Wire council `risk_hints` into coordinator sizing and cooldowns.
2. Feed real per-worker performance into `StrategyCouncil`.
3. Add local `HummingbotV2IntentAdapter` for `position`, `twap`, `grid`, `dca`, `xemm`, and `arbitrage`. Implemented as plan-only.
4. Add `WORKER-SUPERTREND` and `WORKER-BOLLINGER`. Implemented and wired into council/Queen scoring.
5. Clean-room Freqtrade-style pair protections into SwarmGuard/DataStoreAgent. Implemented and connected to DataStore/SwarmGuard.
6. Add data and visual planes for integrations. Implemented with `/integration_planes.json`, `/worker_planes.json`, `/integration_controls`, and `/integrations`.
7. Add Hummingbot lifecycle controls. Implemented with persisted create/monitor/stop/retry/close and gated sidecar command execution.
8. Add public-bot backtest export/ingest. Implemented as sidecar files plus metrics ingestion.
9. Persist worker performance. Implemented with the `worker_performance` SQLite table.
10. Add market-making quote-quality advisors. Implemented as watch-only PMM advisors.

## Remaining Gaps

- Hummingbot live sidecar execution is available only through explicit config. The included runner is a safe template; real Hummingbot process/container orchestration still needs deployment-specific wiring.
- Public-bot metrics now update worker weighting and promotion evidence, but they should be reviewed before enabling fully automatic promotion policies.
- Market-making advisors produce watch-only quote plans and still do not place quotes.
