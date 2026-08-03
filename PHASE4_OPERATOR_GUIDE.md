# Hivenance Phoenix Phase 4 Operator Guide

## Purpose

Phase 4 determines whether any `model_id × order_policy` candidate survives adversarial research
checks after Phase-3 execution costs. It does **not** prove future profitability and cannot authorize
paper, shadow or live execution by itself.

## Install

```bash
python3 -m venv .venv-phase4
source .venv-phase4/bin/activate
python -m pip install -r requirements-phase4.txt
```

## Required preflight

```bash
python scripts/phase0_preflight.py
python scripts/phase1_preflight.py
python scripts/phase2_preflight.py
python scripts/phase3_preflight.py
python scripts/phase4_preflight.py
PYTHONPATH=. pytest -q
```

## Validate existing evidence

This mode makes no public venue request and creates no new Phase-3 simulations:

```bash
python scripts/run_phase4_validation.py --validate-only --once
```

Full report:

```bash
python scripts/run_phase4_validation.py --validate-only --once --json
```

Use a specific database:

```bash
python scripts/run_phase4_validation.py \
  --database data/hivenance.db \
  --validate-only \
  --once \
  --json
```

## Drive the complete research chain

```bash
python scripts/run_phase4_validation.py --once
```

This may fetch public market data, settle forecasts and create new deterministic simulations before
running the tribunal. It still does not use private credentials or submit orders.

## Candidate definition

A candidate is one frozen combination:

```text
model_id × order_policy
```

Examples:

```text
breakout_continuation_v1::market
breakout_continuation_v1::passive_post_only
exhaustion_mean_reversion_v1::marketable_limit
```

Cost scenarios are evidence conditions, not separate candidates.

## Tribunal methods

### Purged walk-forward

Evidence is sorted chronologically. Each test fold is evaluated only after earlier training evidence.
Training labels whose outcome windows approach or overlap the test boundary are purged. The report
also records an embargo boundary for later extensions.

### Symbol holdout

Each symbol is held out in turn. A strategy that only works on one coin is exposed even when its
aggregate mean looks attractive.

### Regime holdout

Phase 4 derives transparent research regimes from the stored volatility-expansion and return-z-score
features:

- `QUIET`
- `EXPANDING`
- `SHOCK_EXPANSION`

These are internal research labels, not claims about a universal market-regime taxonomy.

### Moving-block bootstrap

Contiguous blocks of trade outcomes are resampled to retain some local dependence. The 95% interval
for mean net basis points must have a positive lower bound for a candidate to pass the default gate.

### Threshold-neighbour perturbation

The selection layer is rerun around neighbouring probability and expected-net thresholds. This tests
whether a result disappears after a small decision-boundary movement. It is a decision-threshold
stability test, not a full refit of every internal model parameter.

### Deflated Sharpe Ratio

Phase 4 uses non-annualized trade-level Sharpe, cross-trial Sharpe dispersion, sample length, skewness
and kurtosis. The DSR probability is a multiple-testing diagnostic, not an expected return forecast.

### CSCV-style PBO estimate

Candidate strategies are evaluated across symmetric combinations of contiguous time slices. The best
in-sample candidate is ranked out of sample. The reported PBO is the fraction of selections landing
below the out-of-sample median.

The implementation is explicitly labeled `CSCV_STYLE_CONTIGUOUS_SLICES`. Sparse or unbalanced live
evidence may not satisfy ideal CSCV assumptions, in which case the report remains conservative.

## Default gates

A candidate must satisfy all configured requirements, including:

- at least 100 completed normal-cost simulations;
- at least 14 distinct UTC evidence days;
- positive 95% block-bootstrap lower bound;
- at least 60% positive walk-forward test folds;
- at least 70% positive threshold neighbours;
- symbol positive-profit concentration no greater than 25%;
- month positive-profit concentration no greater than 35%;
- DSR probability at least 95%;
- positive mean at 1.5× cost;
- no catastrophic mean at 2× cost;
- acceptable symbol and regime holdouts;
- global PBO no greater than 20%;
- zero execution-wiring violations;
- zero real orders.

## Outputs

Phase 4 can output:

```text
ready_for_phase5_review = true
```

It can never output:

```text
execution_eligible = true
```

A human must inspect the complete evidence, methodology limits and concentration risks before Phase 5.

## Method references

- David H. Bailey and Marcos López de Prado, *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality*.
- David H. Bailey, Jonathan Borwein, Marcos López de Prado and Qiji Jim Zhu, *The Probability of Backtest Overfitting*.
