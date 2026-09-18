# Phoenix Relative-Value Laboratory — Phase 2 Status

**Phase:** Pair Laboratory  
**Status:** implementation complete, runtime validation pending

## Implemented

- synchronized positive-price cleaning
- log-price transformation
- return correlation diagnostic
- OLS hedge ratio and intercept
- residual spread construction
- spread mean/std/current z-score
- AR(1) spread fit
- OU-style mean-reversion speed estimate
- equilibrium estimate
- mean-reversion half-life
- split-window structural-break diagnostic
- composite stability score
- explicit rejection reasons
- research-only Pair Relationship Crystal
- N-asset unique-pair graph
- direct-route annotation
- Horizon-backed one-shot scanner
- SQLite pair-lab registry
- human-readable pair-lab report

## Scientific boundary

This implementation is deliberately transparent and dependency-light.

It does **not** claim that:
- AR(1) residual mean reversion proves cointegration;
- a stable in-sample pair is profitable;
- an eligible pair should be traded;
- the composite stability score is calibrated probability;
- the split-window break score replaces formal change-point testing.

The current pair lab is a screening and falsification organ.

## Next hardening

Before Phase 2 is declared fully validated:

1. run repository tests in the target Termux/runtime;
2. run the scanner against warmed Horizon history;
3. inspect whether known synthetic mean-reverting pairs pass and diverging pairs refuse;
4. add optional stronger statistical challengers when dependencies are deliberately available:
   - Augmented Dickey-Fuller;
   - Engle-Granger residual stationarity;
   - Johansen for multi-asset research;
   - formal change-point tests;
5. compare stdlib estimates with challenger implementations;
6. persist disagreement rather than averaging contradictions away.

## Acceptance

Phase 2 runtime acceptance requires:

- authority tests PASS;
- microstructure tests PASS;
- pair-lab tests PASS;
- scanner completes against real Horizon DB;
- at least two assets have sufficient warmed history;
- each pair emits either ELIGIBLE or REFUSE with reasons;
- every crystal has execution_eligible=false;
- no private API keys or order actions are used.

## Phase 3 handoff

Only Pair Relationship Crystals that remain eligible and fresh may seed Phase 3 forward-return forecasts.

Phase 3 still must predict future relative return prospectively. Pair eligibility alone is never called edge.
