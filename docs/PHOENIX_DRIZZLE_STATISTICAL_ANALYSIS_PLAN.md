# Phoenix Drizzle Hypothesis — Statistical Analysis Plan

**Status:** pre-registered before Experiment D result review  
**Authority:** research evidence only; no execution or promotion authority  
**Experiments:** A independent streak, B absolute rotation, C relative full-switch, D inventory drizzle

## Core hypothesis

Small, repeated relative-value dislocations across a volatile crypto basket can be harvested after realistic modeled trading friction when relative cheapness identifies the candidate, an early relative streak/turn provides timing, trading is selective enough to avoid churn, inventory is tilted rather than fully switched, and route/spread/fee costs are included before admission.

The hypothesis is not considered supported merely because a wallet finishes positive.

## Primary questions

### H1 — signal existence
Does a relative-cheapness + turn/streak event predict positive future pair-relative movement at 10s, 30s and 60s?

Primary event metric: gross pair-relative capture, bps, measured after signal time with no lookahead.

### H2 — economic harvestability
Does the signal remain positive after the experiment's modeled route cost?

Primary economic event metric: net pair-relative capture at 30s, bps.

Primary portfolio metric: D mutation final equity minus equal-weight inventory_hold final equity.

### H3 — architecture refinement
Do successive controls reduce economically harmful churn and/or improve cost-adjusted edge?

Comparisons:
- A raw streak vs stricter worker mutations.
- B naive rotation vs cost hysteresis vs swarm hysteresis.
- C naive relative switching vs streak vs relative hysteresis.
- D naive inventory vs band vs streak vs swarm streak vs equal-weight hold.

## Pre-specified primary D candidate

inventory_streak is the primary D candidate because it directly represents the hypothesis: relative cheapness + relative turn + streak persistence + cost-aware small inventory tilt.

inventory_swarm_streak is a secondary candidate. inventory_naive and inventory_hold are controls.

## Primary D endpoint

Mean 30-second net pair-relative capture for inventory_streak.

Supportive conditions:
- bootstrap 95% CI lower bound > 0 bps;
- sign/binomial evidence is directionally consistent;
- final portfolio excess versus inventory_hold > 0 USD.

A single 15-minute run is discovery evidence, not definitive proof. Even a positive primary endpoint requires independent repeated runs before promotion.

## Secondary endpoints

- 10s and 60s net pair-relative capture.
- median net capture.
- positive-capture rate.
- gross capture before costs.
- cost per rebalance.
- profit/excess per 100 bps of turnover.
- rebalances per minute.
- direct-pair vs USD-routed capture.
- relative-cheapness bucket.
- streak-persistence bucket.
- 30s capture by Horizon micro/meso/macro context.
- Horizon target alignment.
- transition-specific capture, with minimum sample counts.

## Dependence and autocorrelation

One-second observations and overlapping 10/30/60s outcomes are not independent.

Therefore:
- trade/signal events are the base observations;
- primary uncertainty uses moving-block bootstrap confidence intervals;
- IID intervals are diagnostic only;
- repeated whole-run experiments are required later for between-run inference.

Default event block length: contiguous blocks of 5 trades when event timestamps cannot reliably define 30-second blocks.

## Multiple comparisons

Only the pre-specified D 30s inventory_streak endpoint is primary.

All mutation, transition, cheapness, persistence, route and Horizon subgroup analyses are exploratory. Exploratory p-values must be adjusted with Benjamini-Hochberg FDR.

## Cost accounting

Report gross market contribution, modeled fee cost, modeled spread/route cost, and net outcome separately.

For maker economics: never assume an unverified maker fee; report break-even maker fee per side; any configured maker fee is counterfactual only.

## Controls and counterfactuals

Required:
- equal-weight hold in D;
- stable/no-trade controls from earlier experiments;
- random throttle/control where available;
- naive high-turnover variants;
- cost-free counterfactual only to diagnose signal versus friction.

Cost-free results are never the headline result.

## Anti-overfitting checks

- retain every failed mutation and negative crystal;
- no threshold tuning on the same run can be called validation;
- any refinement from A-D must face a fresh prospective run;
- report with and without the most profitable symbol/transition;
- leave-one-symbol-out sensitivity;
- direct-pair-only and routed-only sensitivity;
- first-half vs second-half stability;
- reject conclusions that depend on one transition, one asset, or one short burst.

## Decision framework after A-D

### NOT SUPPORTED
Use when D primary mean 30s net capture is <= 0, or positive results disappear after cost, block bootstrap, hold comparison or leave-one-symbol-out checks, or apparent performance is dominated by one outlier transition.

Action: diagnose whether failure is signal timing, cost model, route, horizon mismatch or selection; refine only the implicated mechanism; run a fresh prospective experiment.

### PROMISING BUT UNPROVEN
Use when D primary mean 30s net capture is > 0 and evidence survives basic sensitivity checks, but confidence intervals cross zero or sample/run count is insufficient.

Action: freeze parameters and run repeated prospective sessions across different regimes/times. Do not promote authority.

### SUPPORTED AS A RESEARCH HYPOTHESIS
Use only when net event capture is positive after modeled costs, block-bootstrap intervals are materially above zero across repeated prospective runs, excess vs hold is positive across runs, the effect is not dominated by one symbol/transition, and first/second-half plus leave-one-symbol-out checks survive.

This still does not imply live profitability under real fills.

## Required final report

1. Executive hypothesis verdict.
2. Experiment A-D economic table.
3. Gross vs cost decomposition.
4. Turnover/churn progression A-D.
5. Event capture distributions.
6. Block-bootstrap confidence intervals.
7. Positive-capture rates and exact binomial tests.
8. Mutation comparisons.
9. Cheapness/streak bucket response curves.
10. Route economics.
11. Horizon-context counterfactual.
12. Leave-one-symbol-out sensitivity.
13. First-half / second-half stability.
14. Multiple-comparison-adjusted exploratory findings.
15. Failure mode diagnosis.
16. Refinement proposal.
17. Prospective validation protocol.

No production learning or execution-policy promotion is authorized by this analysis.