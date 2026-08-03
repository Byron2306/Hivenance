# Profitability Gap Improvement Plan

Date: August 3, 2026

## Purpose

This document explains how Hivenance can improve its current profitability gap without weakening governance discipline.

The system is already strong at:

- authority separation
- auditability
- observation quality
- execution simulation
- promotion control

The main weakness is not safety.
The main weakness is that broad, repeatable, post-cost edge has not yet been proven.

## Core diagnosis

Right now the system behaves more like a very good research court than a capital allocator with verified edge.

The profitability gap is being driven by five problems:

1. too many Phase 2 ideas are still weak after costs
2. candidate intake is selective, but the upstream idea pool is still not rich enough
3. some positive pockets are narrow and sample-thin
4. summary views have only recently become statistically honest
5. the system is not yet adapting capital permission based on enough settled forward evidence

## Improvement principle

Do not chase more activity.
Chase more selective permissioning.

Profit should come from:

- better abstention
- stronger regime-symbol-thesis matching
- better microstructure survivability
- faster demotion of weak slices
- deeper exploitation of the small slices that actually survive cost

## Priority roadmap

## Priority 1: Strengthen thesis-family x regime x symbol-class evidence

### Goal

Stop thinking in terms of "best model overall".
Start scoring edge at the slice level:

- thesis family
- regime
- cohort bucket
- symbol
- horizon
- execution policy

### Why this matters

A model can be mediocre overall and still be valuable in one narrow market condition.
That is how real trading systems often become profitable.

### Required work

- add durable slice-level scorecards for `thesis x regime x cohort x symbol class`
- rank by weighted post-cost realized net, not just global model means
- require minimum settled counts before a slice can influence Phase 3 intake
- add explicit slice demotion when recent evidence decays

### Expected benefit

More capital and simulation budget will flow toward real edge pockets instead of average behavior.

## Priority 2: Improve Phase 2 recovery logic with evidence feedback

### Goal

The new adaptive recovery system should not stay static.
It should learn whether recovered candidates actually outperform standard candidates.

### Required work

- store adaptation strength and adaptation type per recovered forecast
- compare adapted versus standard outcomes by cohort and policy
- automatically reduce adaptation strength where adapted candidates underperform
- automatically increase adaptation strength where adapted candidates show stable positive post-cost outcomes
- enforce minimum sample thresholds before any adaptation policy changes

### Expected benefit

The system will stop treating all recoveries equally and will become more selective about when loosened research gates are worth it.

## Priority 3: Add recency-weighted profitability gates

### Goal

A stale edge should not dominate a fresh losing regime.

### Required work

- compute rolling recent realized edge windows for Phase 2 and Phase 3
- add decayed weighting so recent results matter more than old results
- require both long-run and recent positive evidence for promotion
- add drift alarms for slices whose recent realized edge falls below threshold

### Expected benefit

The system becomes better at surviving edge decay instead of clinging to old winners.

## Priority 4: Tighten Phase 3 from "best candidate" to "best executable candidate"

### Goal

Phase 3 should rank ideas by execution survivability, not just research attractiveness.

### Required work

- expand edge-quality ranking to include:
  - recent slice-level realized net
  - fill survivability
  - cost volatility
  - scenario robustness
  - stress deterioration rate
- add penalties for candidates that only win in one policy or one scenario
- add penalties for candidates that collapse under modest cost multipliers
- prefer candidates with multiple policy paths to positive net

### Expected benefit

The execution lab spends more time on ideas likely to survive real friction.

## Priority 5: Build microstructure-aware symbol specialization

### Goal

Different symbols deserve different thesis families and policy treatment.

### Required work

- cluster symbols into behavior classes:
  - ultra-liquid majors
  - event-spike alts
  - mean-reverting liquid pairs
  - unstable spread / hostile liquidity pairs
- map allowed thesis families and preferred order policies to each class
- penalize using a thesis family outside its proven symbol class
- allow special fast-lane simulation for classes with repeated success

### Expected benefit

The system stops treating all markets like the same game.

## Priority 6: Promote policy families, not just models

### Goal

Some of the best current results appear to come from execution policy interacting with model forecasts.

### Required work

- define candidate keys as:
  - `model x policy x scenario robustness x regime slice`
- persist policy-level leaderboards by cohort and symbol class
- let governance approve a policy family even if the raw model is only moderately good overall
- demote models whose positive results disappear once policy advantage is removed

### Expected benefit

Hivenance can capture execution-mediated edge instead of missing it by over-focusing on raw forecast quality.

## Priority 7: Improve negative learning

### Goal

Losing ideas should teach the system faster.

### Required work

- tag losses by failure type:
  - spread too wide
  - slippage too hostile
  - late entry
  - wrong regime
  - false breakout
  - reversion fade failure
- aggregate failure causes by cohort and symbol class
- feed those causes back into:
  - Phase 1 filtering
  - Phase 2 abstention rules
  - Phase 3 policy ranking

### Expected benefit

The system improves by removing bad subspaces, not just by searching for more good ones.

## Priority 8: Raise the bar for "profitable"

### Goal

A thin positive pocket should not be confused with deployable edge.

### Required work

- require all profitability claims to satisfy:
  - minimum settled sample count
  - minimum recent sample count
  - positive mean net after cost
  - bounded tail loss
  - multi-scenario survivability
  - non-trivial fill ratio
  - low symbol concentration
- mark pockets as:
  - exploratory
  - promising
  - candidate
  - promotion-eligible

### Expected benefit

More honest capital gating and less risk of self-deception.

## Priority 9: Use sidecars as challengers, not decoration

### Goal

The integrations should sharpen edge discovery.

### Required work

- ingest sidecar outputs as challenger evidence for specific thesis families
- compare sidecar proposals against native and federated models by slice
- only preserve sidecar-derived signals when they improve post-cost outcomes
- turn public-bot evidence into structured challenger priors, not global trust boosts

### Expected benefit

External research tools become useful only where they add measurable value.

## Priority 10: Build a capital-allocation brain after edge exists

### Goal

Do not scale models.
Scale validated edge slices.

### Required work

- build a routing layer that allocates simulation budget, shadow budget, and future capital budget by slice score
- use capped exposure per thesis family
- add automatic downweighting after recent deterioration
- add diversity constraints so one symbol or one thesis cannot dominate

### Expected benefit

When profitable slices finally appear, the system will know how to exploit them safely.

## Concrete sequence

Recommended order of implementation:

1. slice-level evidence tables and scorecards
2. recency-weighted profitability and drift metrics
3. adaptive recovery feedback loop
4. policy-family promotion logic
5. symbol-class specialization
6. richer failure taxonomy
7. allocation layer for simulation and future capital

## What not to do

Do not:

- loosen all thresholds globally
- increase trade frequency just to create more activity
- trust raw positive mean net without sample depth
- bypass abstention discipline
- promote a model because one scenario or one policy looks strong
- treat synthetic validation as deployable profit proof

## Success criteria

This profitability gap is improving when the system starts to show:

- fewer but better non-abstain forecasts
- more consistent positive post-cost Phase 3 pockets
- stronger adapted-versus-standard comparisons
- lower fragility in Phase 4
- at least one repeatable slice with enough depth to survive governance review
- promotion candidates that remain positive under recency weighting and stress

## Honest target

Near-term target:

- move from "interesting but weak broad edge" to "one or two narrow but honest edge slices"

Medium-term target:

- convert those narrow slices into governance-approved shadow candidates

Long-term target:

- build a regime-aware internal edge marketplace where capital follows only repeatedly validated slices

## Closing view

Hivenance does not need to become less governed to become more profitable.

It needs to become better at:

- identifying narrow real edge
- preserving only the slices that survive truth
- killing weak slices quickly
- routing trust and eventually capital with much finer precision

That is the path from a strong research platform to a real governed profit engine.
