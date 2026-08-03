# Hivenance Phoenix Phase 4 Changelog

## Release

**Phase:** 4  
**Name:** Adversarial Validation Tribunal  
**Mode:** research review only  
**Execution wired:** false  
**Real orders submitted:** 0  
**Automatic promotion:** forbidden

## Added

### Adversarial validation engine

Added `strategies/volatility_breakout/adversarial_validation.py` with:

- chronological purged walk-forward evaluation;
- recorded purge and embargo boundaries;
- leave-one-symbol-out holdouts;
- leave-one-volatility-regime-out holdouts;
- moving-block bootstrap confidence intervals for mean net basis points;
- threshold-neighbour perturbation across probability and expected-net gates;
- non-annualized trade-level Sharpe diagnostics;
- Deflated Sharpe Ratio probability using the observed trial dispersion, skewness and kurtosis;
- a contiguous-slice CSCV-style Probability of Backtest Overfitting estimate;
- symbol and calendar-month positive-profit concentration checks;
- normal, 1.5× cost and 2× cost scenario comparison;
- immutable gate reasons for every rejected candidate.

### Validation agent

Added `ValidationLabAgent`:

- optionally drives the public Phase 1 → Phase 2 → Phase 3 chain;
- supports validate-only operation on existing Phase-3 evidence;
- publishes validation snapshots and health events;
- can only emit a Phase-5 **review recommendation**;
- cannot enable execution or promote a strategy.

### Durable evidence

Added SQLite projections:

- `phase4_validation_runs`
- `phase4_candidate_results`
- `phase4_fold_results`
- `phase4_holdout_results`
- `phase4_perturbation_results`

The source Phase-3 simulation and Phase-2 forecast records remain unchanged.

### Standalone tooling

Added:

- `scripts/run_phase4_validation.py`
- `scripts/phase4_preflight.py`
- `requirements-phase4.txt`
- `config/volatility_breakout_phase4.yaml`

### Desktop UI

Added the **Validation** page with:

- tribunal status;
- candidate count;
- PBO estimate;
- Phase-5 review gate;
- bootstrap lower bound;
- DSR probability;
- walk-forward positive-fold ratio;
- symbol-profit concentration;
- immutable failure reasons;
- permanent zero-real-order indicators.

## Changed

- Advanced `phoenix_phase` from 3 to 4.
- Phase-3 preflight now accepts later Phoenix phases while still enforcing all Phase-3 safety invariants.
- Coordinator starts Phase 4 as the outermost research agent, allowing it to drive the earlier public research chain on schedule.
- README and Ember strategy documentation now describe the full Phase 1–4 pipeline.

## Safety invariants retained

- Phase-0 quarantine remains active.
- Dry run remains enabled.
- Live mode remains disabled.
- On-chain execution remains disabled.
- Leverage remains 1×.
- Small-trade bypass remains disabled.
- Automatic public-bot promotion remains disabled.
- Phase-4 code imports no exchange client or execution agent.
- Phase 4 never mutates the live `orders`, `fills` or balance tables.
