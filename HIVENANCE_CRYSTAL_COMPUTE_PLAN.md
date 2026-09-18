# Hivenance Crystal Compute Plan

## Purpose

Borrow the strongest parts of BEAST's crystal compute and deterministic intelligence stack without importing its coding-specific complexity.

For Hivenance, this means:

- reuse verified research outcomes before spending more model or simulation compute
- prefer deterministic transforms and cheap local logic before expensive inference
- bind reuse to regime, symbol class, configuration, and evidence freshness
- persist receipts for every reuse decision

This is a governance and efficiency layer, not a shortcut around trading evidence.

## Core Principle

Every expensive research step should answer:

1. Have we already solved this exact governed problem?
2. Have we solved a semantically close version under the same regime and policy surface?
3. Can a deterministic transform answer it instead?
4. Can a cheaper local route answer it?
5. Only then should we spend expensive inference or larger simulation budgets.

## Hivenance Mapping

### Phase 2

Use crystal compute for:

- exact reuse of prior forecast evidence by model, symbol, regime hint, and config hash
- deterministic feature transforms and ranking enrichments
- cheap-vs-expensive research routing
- repeatable failure-cause learning

### Phase 3

Use crystal compute for:

- reuse of prior execution-policy outcomes by symbol class, regime, and venue profile
- deterministic fill/slippage assumption selection
- simulation-priority ranking

### Phase 4

Use crystal compute for:

- reuse of previously validated scenario slices
- deterministic candidate filtering before full adversarial validation

### Phase 5

Use crystal compute for:

- reuse of shadow-flight policy envelopes and known bad contexts
- freeze-aware evidence continuity

## First Narrow Implementation

The first implementation must be advisory only.

It should:

- create governed research reuse receipts
- bind reuse context to:
  - model id
  - symbol
  - regime hint
  - horizon
  - config hash
- summarize prior settled evidence:
  - sample count
  - mean realized net bps
  - win rate
  - latest settled timestamp
- classify each request as:
  - `exact_reuse_candidate`
  - `exact_reuse_too_weak`
  - `no_prior_evidence`
- persist every decision
- expose summaries in Phase 2 and Phase 3 payloads

It must not:

- auto-promote forecasts
- alter order submission authority
- bypass Phase 4 or Phase 5 gates
- rewrite realized outcomes

## Next Integration Steps

### Step 1

Advisory reuse receipts in Phase 2 and summary rollups in Phase 3.

### Step 2

Deterministic routing ladder:

- exact reuse
- deterministic transform
- local lightweight research route
- full hypothesis competition

### Step 3

Execution policy reuse:

- symbol class
- regime hint
- venue profile
- spread/depth band

### Step 4

Validation reuse:

- only reuse scenario slices when config hash, candidate family, and evidence freshness all match

## Guardrails

- reuse must be revocable by config drift
- reuse must be auditable in the database
- reuse can inform decisions before it replaces decisions
- live phases still require human approval and existing phase gates
