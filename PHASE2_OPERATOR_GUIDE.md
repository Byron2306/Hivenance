# Hivenance Phoenix Phase 2: Hypothesis Foundry operator guide

## Purpose

Phase 2 turns Phase-1 observations into competing, timestamped predictions. It does not trade.
It answers a narrower question: do breakout continuation or exhaustion mean reversion show
repeatable, cost-adjusted predictive value compared with simple baselines?

## Safety invariants

```yaml
phoenix_phase: 2
phase0_quarantine: true
dry_run: true
live_mode: false
auto_trading_enabled: false
onchain_enabled: false
phase2_hypotheses_enabled: true
public_bot_metrics_auto_promote: false
swarmguard_small_trade_bypass: false
hummingbot_sidecar_live_enabled: false
hummingbot_v2_leverage: 1
```

Every run and forecast records:

- `execution_wired: false`
- `execution_eligible: false`
- `orders_submitted: 0`
- `order_intent: null`

## Minimal launch

```bash
python3 -m venv .venv-phase2
source .venv-phase2/bin/activate
python -m pip install -r requirements-phase2.txt

python scripts/phase0_preflight.py
python scripts/phase1_preflight.py
python scripts/phase2_preflight.py
python scripts/run_phase2_hypotheses.py --once
```

Continuous mode:

```bash
python scripts/run_phase2_hypotheses.py
```

Full JSON cycle, settlement and scorecard:

```bash
python scripts/run_phase2_hypotheses.py --once --json
```

## Primary hypotheses

### Breakout continuation

Requires complete high-quality data, volatility expansion, elevated participation, a material
directional move and a projected movement large enough to beat estimated cost by the configured
multiple. Book imbalance and trend alignment influence score but cannot replace the core gates.

### Exhaustion mean reversion

Requires an extreme standardized move near the recent range edge plus a first sign of exhaustion,
such as a one-bar reversal or opposing book imbalance. It does not blindly fade strong momentum.

The models never blend or choose whichever explanation wins afterward.

## Baselines

- `baseline_no_trade_v1`
- `baseline_simple_momentum_v1`
- `baseline_simple_mean_reversion_v1`
- `baseline_deterministic_random_v1`

A primary model that cannot beat these after costs has not demonstrated useful edge.

## Forecast horizons

```yaml
phase2_horizons_seconds: [300, 900, 3600]
```

Each forecast is persisted before its future outcome exists. Settlement uses the first persisted
observation at or after the target timestamp, within the configured tolerance.

## Cost model

The research hurdle includes:

- two taker-fee sides;
- observed spread;
- square-root depth participation impact;
- latency buffer;
- safety buffer.

The defaults are deliberately conservative research assumptions and must later be replaced or
validated against venue-specific fee tiers and shadow execution evidence.

## Scorecard

For each model Hivenance reports:

- total forecasts and non-abstain rate;
- settled research bets;
- cost-adjusted win rate;
- mean and cumulative net basis points;
- Brier score;
- mean absolute movement error.

Probabilities remain `COLD_START_PROVISIONAL`. Phase 2 measures calibration; it does not pretend
calibration exists before evidence accumulates.

## Phase 3 review gate

The default gate requires:

- at least 300 forecasts;
- at least 100 settled non-abstain forecasts;
- at least 14 distinct UTC research days;
- zero execution wiring or orders;
- a primary model with positive mean net outcome after estimated costs;
- the best primary model to beat the best settled baseline.

This only produces `ready_for_phase3_review`. Human review remains mandatory and execution
eligibility remains false.

## Known boundaries

- REST polling is still used; true sequential order-flow imbalance remains unavailable.
- Venue count remains one per process.
- DOWN predictions are evaluated synthetically for hypothesis comparison. Phase 2 does not imply
  short selling, margin or derivative support.
- Cost assumptions are research estimates, not measured fill costs.
- No profitability claim is made.
