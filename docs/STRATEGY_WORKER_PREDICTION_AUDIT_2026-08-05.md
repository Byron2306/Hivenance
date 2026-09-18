# Strategy Worker Prediction Audit

Date: 2026-08-05

## Executive Read

Byron's concern is valid: Hivenance has been treating the strategy workers too
much like decorative voters and too little like specialized predictive
instruments.

The current codebase has two worker layers:

1. Legacy council workers: `WORKER-SMA`, `WORKER-RSI`, `WORKER-RSI2`,
   `WORKER-BREAKOUT`, `WORKER-MOMENTUM`, `WORKER-BOLLINGER`,
   `WORKER-SUPERTREND`, `WORKER-VOL-EXPANSION`, `WORKER-EXIT-RISK`,
   `WORKER-PROTECTION`, and `WORKER-LATENCY`.
2. Governed Phase-2 research models: native breakout/reversion models,
   Freqtrade/Jesse/FreqAI/FinRL/MacroHFT/WebCrypto/CEX-oracle/Triune adapters,
   plus baselines.

The problem is not that the worker ideas are bad. The problem is that the older
workers mostly vote in the older council/coordinator stack, while Phase 2/3 gate
evidence is driven by the newer research-model layer. That means the UI can show
busy workers while the governed profit gates are mostly scoring different
objects.

## Local Evidence Snapshot

Generated with:

```bash
./.venv-phase1/bin/python scripts/audit_strategy_workers.py --database data/swarm_data.db
```

Current model-level evidence from recent settled outcomes:

| Model | Settled | Wins | Win Rate | Mean Net Bps | Read |
| --- | ---: | ---: | ---: | ---: | --- |
| `adapter_freqtrade_breakout_v1` | 9 | 5 | 55.6% | +27.26 | promising but tiny sample |
| `candidate_finrl_conservative_policy_proxy_v1` | 678 | 185 | 27.3% | -31.32 | broadly negative |
| `candidate_freqai_transparent_linear_v1` | 824 | 208 | 25.2% | -31.83 | quarantined correctly |
| `candidate_webcrypto_market_context_proxy_v1` | 48 | 13 | 27.1% | -37.94 | broad model negative |
| `adapter_jesse_trend_pullback_v1` | 8 | 2 | 25.0% | -57.65 | no current evidence edge |

Positive slices:

| Slice | Settled | Wins | Mean Net Bps | Read |
| --- | ---: | ---: | ---: | --- |
| `Freqtrade breakout / 300s / UP` | 3 | 2 | +101.08 | very promising, too small |
| `WebCrypto context / 3600s / DOWN` | 8 | 5 | +84.92 | promising, still narrow |
| `Freqtrade breakout / 900s / UP` | 3 | 2 | +67.28 | promising, too small |
| `WebCrypto context / 900s / DOWN` | 7 | 2 | +11.50 | positive mean, weak win rate |

Recent activation:

| Model | Recent Forecasts | Active | Activation |
| --- | ---: | ---: | ---: |
| `breakout_continuation_v1` | 1807 | 0 | 0.0% |
| `exhaustion_mean_reversion_v1` | 2091 | 0 | 0.0% |
| `adapter_jesse_trend_pullback_v1` | 285 | 0 | 0.0% |
| `candidate_cex_multi_horizon_oracle_v1` | 900 | 2 | 0.2% |
| `candidate_finrl_conservative_policy_proxy_v1` | 2091 | 282 | 13.5% |
| `candidate_freqai_transparent_linear_v1` | 1047 | 180 | 17.2% |

Interpretation:

- The Freqtrade-style breakout adapter is the only model currently positive at
  model level, but the sample is too small to promote.
- WebCrypto is broadly negative but has a strong `DOWN` pocket. That should
  become a slice-specialist scout, not a broad model.
- FinRL and FreqAI are currently generating lots of negative evidence. The
  FreqAI quarantine remains justified.
- Native breakout and reversion are currently too strict or mismatched to the
  live feature/regime feed.
- The old named workers are not first-class Phase-2 candidates, so their
  predictive strengths are not being properly settled, calibrated, or promoted.

## External Research Takeaways

FreqAI's real architecture is not just a hand-written linear score. It is built
around retraining predictive ML models, large feature sets, realistic retraining
backtests, outlier removal, normalization, dimensionality reduction, and live
inference separation. Source: Freqtrade FreqAI docs,
https://www.freqtrade.io/en/stable/freqai/.

Hummingbot Strategy V2 controllers are production-grade sub-strategy modules
that consume market data providers and emit executor actions. Source:
Hummingbot controller docs,
https://hummingbot.org/strategies/v2-strategies/controllers/.

Recent limit-order-book research warns that high forecast accuracy does not
automatically imply executable trading value, and that operational evaluation
must ask whether a forecast can complete a transaction profitably. Source:
Deep Limit Order Book Forecasting,
https://arxiv.org/html/2403.09267v4.

Recent crypto microstructure work suggests better input processing can matter
more than adding another complex model. Savitzky-Golay style filtering improved
binary up/down prediction materially in the reported crypto LOB experiments.
Source: Exploring Microstructural Dynamics in Cryptocurrency Limit Order Books,
https://arxiv.org/html/2506.05764v2.

Triple-barrier labeling and meta-labeling are a better fit for Hivenance than
fixed-horizon "was price higher later?" labels because they label whether a
trade would hit a target, stop, or time barrier. Source: mlfinpy labeling docs,
https://mlfinpy.readthedocs.io/en/latest/Labelling.html.

## What This Means For Hivenance

The strategy workers should stop being generic voters and become specialized
predictors with their own settled labels.

Required shift:

```text
worker says BUY/SELL/HOLD
-> persist worker forecast receipt
-> label with triple barrier outcome
-> train/calibrate meta-label per worker/symbol/regime/horizon
-> only admit worker when its current slice beats costs
```

## Worker Upgrade Plan

### 1. Promote Legacy Workers Into Phase-2 Forecast Producers

Create a `WorkerSignalFederation` that wraps each legacy worker into a Phase-2
research model:

- `WORKER-BREAKOUT` becomes a breakout specialist.
- `WORKER-MOMENTUM` becomes short-horizon continuation specialist.
- `WORKER-RSI`, `WORKER-RSI2`, and `WORKER-BOLLINGER` become reversion
  specialists.
- `WORKER-SUPERTREND` and `WORKER-SMA` become trend-state specialists.
- `WORKER-VOL-EXPANSION` becomes an event/volatility expansion specialist.
- `WORKER-EXIT-RISK`, `WORKER-PROTECTION`, and `WORKER-LATENCY` become
  veto/meta-label workers, not directional alpha workers.

Authority remains `research_forecast_only`.

### 2. Add Worker Receipts

Persist one object per worker forecast:

```json
{
  "schema": "hivenance_worker_forecast_receipt_v1",
  "worker_id": "WORKER-BREAKOUT",
  "symbol": "BTC/USD",
  "horizon_seconds": 300,
  "direction": "UP",
  "raw_action": "BUY",
  "raw_strength": 0.72,
  "regime_hint": "trend_expansion",
  "symbol_class": "core_liquid",
  "feature_root": "sha256:...",
  "cost_bps": 25.4,
  "authority": "research_forecast_only",
  "execution_authority": "none"
}
```

### 3. Replace Fixed-Horizon Labels With Triple-Barrier Labels

Each worker forecast should settle into:

```json
{
  "schema": "hivenance_worker_triple_barrier_outcome_v1",
  "worker_forecast_id": "...",
  "label": "TARGET_HIT|STOP_HIT|TIME_EXPIRED",
  "target_bps": 40.0,
  "stop_bps": 25.0,
  "time_limit_seconds": 900,
  "net_return_bps": 12.4,
  "first_touch_ts": 1785950000.0,
  "fee_spread_slippage_bps": 24.8
}
```

This makes workers predict "would this trade setup complete profitably?" rather
than merely "will price be up later?"

### 4. Add Meta-Label Worker Scoring

For each worker/symbol/regime/horizon slice, compute:

- activation rate
- target-hit rate
- stop-hit rate
- mean net bps
- median net bps
- 1.5x-cost stressed lower bound
- false-positive rate
- information value versus abstention
- decay-adjusted recent performance

Then Phase 3 should receive worker candidates only when their current slice has
enough evidence and a positive stressed lower bound.

### 5. Use Better Inputs Before Bigger Models

Add these features before adding heavier ML:

- filtered order-book imbalance
- imbalance persistence over multiple observations
- spread stability and spread shock
- depth slope and depth asymmetry
- trade/volume impulse decay
- volatility-normalized target and stop widths
- worker disagreement entropy
- regime transition probability

The local `Phase1FeatureEngine` already has top-of-book imbalance and depth, but
it does not yet have enough sequence memory to make the microstructure workers
serious.

### 6. Make FreqAI Real Or Rename It

The current `candidate_freqai_transparent_linear_v1` is honest because it says
`NO_FREQAI_TRAINING_RUNTIME`, but it should not be expected to behave like real
FreqAI.

Upgrade path:

- build a rolling supervised dataset from `hypothesis_forecasts`,
  `hypothesis_outcomes`, and Phase-1 features
- train a small `sklearn`/LightGBM/CatBoost-style classifier if available
- target triple-barrier success, not raw direction
- emit model hash, train window, feature list, and out-of-sample score
- keep it research-only until it beats the transparent proxy prospectively

### 7. Make Hummingbot Useful Before Execution

Hummingbot should not be connected for live execution yet. It should be used as
a richer execution-policy planner:

- translate worker-approved forecasts into `position`, `grid`, `dca`, or `twap`
  executor shapes
- simulate those shapes in Phase 3
- score which executor family rescues or destroys each worker signal
- let Phase 4 validate only `worker x executor` pairs, not model names alone

## Immediate Best Next Move

Build Phase-2 `WorkerSignalFederation` and Phase-3 `worker x executor` scoring.

The highest-value first slice is:

```text
WORKER-BREAKOUT / Freqtrade-style breakout / 300s and 900s / UP
```

The second slice worth controlled exploration is:

```text
WORKER-WEBCRYPTO-CONTEXT / 3600s / DOWN
```

Everything else should either abstain, collect labels, or act as a veto layer.

## Honest Assessment

This will help, but only if we stop pretending every worker is equally useful.
The likely profitability path is not "more agents." It is:

```text
few specialized workers
-> labeled trade-completion outcomes
-> meta-label false-positive suppression
-> worker x execution-policy validation
-> one narrow promoted slice
```

The workers can absolutely become more important. Right now, they need to be
made measurable before they can be made powerful.

## Implementation Update

Implemented first-slice `WorkerSignalFederation` on 2026-08-05:

- Phase 1 now persists compact real OHLCV worker input series in feature values.
- Phase 2 now wraps SMA, RSI, RSI2, breakout, momentum, Bollinger, Supertrend,
  and volatility-expansion workers as research-only forecast models.
- Worker forecasts emit `hivenance_worker_forecast_receipt_v1` receipts with
  deterministic series roots and explicit `execution_authority: none`.
- Worker BUY/SELL proposals that fail cost edge now emit non-executable
  counterfactual settlement rows instead of disappearing as abstentions.
- Expensive transformed-reuse scans are disabled by default until materialized
  reuse statistics exist; exact reuse remains active.
- Regime re-entry scans are bounded to recent evidence so the 16 GB live ledger
  does not block every hypothesis cycle.

Live verification after restart:

```text
Latest worker ledger snapshot:
worker_signal_bollinger_v1        active=6   counterfactual=6
worker_signal_breakout_v1         active=3   counterfactual=3
worker_signal_momentum_v1         active=3   counterfactual=3
worker_signal_rsi2_v1             active=30  counterfactual=30
worker_signal_rsi_v1              active=6   counterfactual=6
worker_signal_sma_v1              active=0   counterfactual=0
worker_signal_supertrend_v1       active=12  counterfactual=12
worker_signal_vol_expansion_v1    active=3   counterfactual=3
```

These rows still cannot execute. Their purpose is to create falsifiable evidence
about whether legacy worker signals predict profitable outcomes after real fees,
spread, latency, and safety costs.
