# Hivenance Phoenix Phase 2 changelog

## Hypothesis Foundry

- Added independent breakout-continuation and exhaustion-mean-reversion research models.
- Added no-trade, simple-momentum, simple-mean-reversion and deterministic-random baselines.
- Added three frozen forecast horizons: 5, 15 and 60 minutes.
- Added explicit abstention reasons rather than silently coercing missing data into neutral values.
- Added cost-adjusted forecasts using round-trip fees, spread, depth-based impact, latency and safety buffers.
- Added provisional probability, uncertainty, model provenance and immutable feature snapshots.

## Research features

- Added short-return z-score, price z-score, range position, normalized trend slope,
  ATR percentage, one-bar reversal, momentum consistency and recent/baseline volume ratio.
- Preserved true order-flow imbalance and trade-count z-score as unavailable until sequential feeds exist.

## Durable truth settlement

- Added `hypothesis_runs`, `hypothesis_forecasts` and `hypothesis_outcomes` SQLite projections.
- Added deterministic forecast IDs and future target timestamps.
- Added automatic settlement against the first persisted observation after the target horizon.
- Added net outcome after estimated costs, Brier score and absolute movement-error attribution.
- Added model scorecards and a Phase-3 review gate requiring primary hypotheses to beat baselines.

## Runtime and operator surfaces

- Added `HypothesisSwarmAgent`, which drives one Observation Swarm schedule without duplicate polling.
- Added standalone `scripts/run_phase2_hypotheses.py` and `scripts/phase2_preflight.py`.
- Added `/hypotheses.json`, coordinator snapshots, heartbeat visibility and an Electron Hypotheses page.
- Preserved Phase-0 quarantine, zero orders, 1x leverage, no DEX, no automatic promotion and no live eligibility.
