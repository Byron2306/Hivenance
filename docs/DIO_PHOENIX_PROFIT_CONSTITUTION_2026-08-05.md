# DIO-Phoenix Profit Constitution

Date: Wednesday, August 5, 2026

## Purpose

Hivenance Phoenix should not try to become profitable by loosening governance.
It should become profitable by making edge narrower, more truthful, more capacity-aware, and more explicitly authorized.

The right target is:

`maximize expected risk-adjusted geometric growth after all costs, only across actions that are presently proven eligible and explicitly authorized`

This means Phoenix remains the stochastic discovery and simulation organism, while a DIO-style deterministic layer becomes the profitability constitution.

## Core thesis

Phoenix already does many hard things well:

- observation and durable evidence capture
- frozen forecasts with later settlement
- simulation under cost and slippage
- adversarial validation and promotion gates
- canary and growth separation
- refusal to pretend weak evidence is live authority

Its weak point is still the profit conversion chain:

`observed market state -> forecast edge -> executable edge -> promoted edge -> scaled capital`

The system therefore needs to become better at six things:

1. refusing false edge earlier
2. proving eligibility more exactly
3. specializing by slice instead of averaging too broadly
4. separating research value from capital value
5. sizing only to proven capacity
6. preserving a hard abstention-first option

## Constitutional structure

### Loop A: stochastic discovery

These systems may search, estimate, compare, and adapt:

- Phase 1 observation
- Phase 2 hypothesis competition
- federated challengers and sidecars
- Phase 3 execution lab
- research allocators and optimizers

They may propose. They may not grant live authority.

### Loop B: deterministic proof and authority

This layer must:

- bind every decision to exact code, config, world state, and evidence
- refuse any candidate with incomplete or stale prerequisites
- verify risk, capacity, concentration, and stage ceilings
- authorize only one bounded action at a time
- turn live outcomes into evidence, not direct authority

## Profit hierarchy

The optimizer must not use a single blended profit score.
It must behave lexicographically.

### Level 0: hard admissibility

No optimization unless all are true:

- evidence chain valid
- world state fresh
- execution environment healthy
- no unresolved incident
- code and config bound
- risk budget available
- capital stage valid
- venue and dependency state acceptable

### Level 1: survival

Hard constraints on:

- drawdown
- daily loss
- CVaR / expected shortfall
- open exposure count
- correlated exposure
- venue concentration
- liquidity participation
- unresolved order state risk

### Level 2: robust growth

Among eligible candidates, maximize robust expected log growth, not raw expected PnL.

This should include:

- return uncertainty
- fill uncertainty
- latency uncertainty
- cost uncertainty
- regime uncertainty
- capacity degradation

### Level 3: capital efficiency

When two candidates are similar on robust growth, prefer:

- lower turnover
- lower liquidity footprint
- lower provenance overlap
- lower execution uncertainty
- simpler causal attribution

### Level 4: information value

Promising but unproven slices may earn:

- observation budget
- simulation budget
- shadow budget

They do not earn live capital merely because they are interesting.

## Hivenance-native object model

The repo does not need to import DIO wholesale. It should adopt the parts that sharpen profit truth.

### 1. Market World State Crystal

Exact current state for an action:

- venue
- symbol
- symbol class
- regime state
- spread and depth
- fee schedule digest
- latency state
- resource pressure
- open exposure digest
- risk-budget digest
- freshness deadline

### 2. Thesis Capability Crystal

Reusable bounded proposition:

- thesis family
- regime scope
- symbol class scope
- horizon
- execution policy family
- evidence minimum
- capacity contract
- abstention conditions
- authority ceiling

### 3. ~~Profitability Slice Posterior~~

The true unit of edge:

`thesis family x regime x symbol class x execution policy x horizon x venue`

Implemented in repo scorecards and candidate-intake objects. It now stores or emits:

- posterior net-return distribution
- lower bound after shrinkage
- probability of positive net
- tail-risk estimate
- execution-success distribution
- capacity curve
- drift state
- evidence strength

### 4. ~~Negative Capability Crystal~~

Implemented in repo scorecards and candidate-intake objects for reusable bad-state knowledge:

- false breakout
- wrong regime
- spread too wide
- insufficient depth
- stale data
- late entry
- venue anomaly
- infrastructure anomaly

These should prune futile slices before simulation and before capital.

## What “better” means in this repo

Better does not mean “more models.”
Better means more selective authority and better capital concentration into slices that survive post-cost reality.

The main upgrades should be:

### 1. Slice-first profitability

Stop treating edge as mostly model-wide.
Promote or demote by:

- thesis family
- regime
- symbol class
- execution policy
- horizon

The same model can be good in one slice and toxic in another.

### 2. Shrinkage before trust

Small-sample winners must be shrunk toward conservative parent priors.
No promotion should rely on raw slice means.

Preferred hierarchy:

`global -> thesis family -> regime -> symbol class -> execution policy -> symbol`

### 3. Sequential evidence, not peek-and-celebrate

Promotion logic should use time-uniform evidence or confidence-sequence style gating, so repeated checking does not silently inflate confidence.

### 4. Capacity-aware profit

Edge at USD 5 is not proof at USD 500.
Each promoted slice needs an observed or simulated capacity curve:

`net edge(size) = gross edge - fees - spread - impact - slippage - latency loss`

### 5. Execution-policy competition

The promoted object should be:

`forecast thesis + execution policy + slice`

not just “model X.”

### 6. Provenance-aware diversification

Allocation should penalize shared:

- features
- data ancestry
- regime classifier
- model family
- venue
- sidecar lineage

Two names are not two independent edges.

### 7. Abstention as a real champion

Cash and no-trade must remain first-class candidates in every optimizer run.
Any live allocation must beat abstention after:

- fees
- spread
- impact
- latency
- uncertainty
- opportunity cost

## Immediate implementation order

These are the highest-value next changes for Phoenix itself.

### Stage A: prove and prune

1. ~~Add world-state eligibility receipts before Phase 3 simulation admission.~~
2. ~~Add negative-capability receipts for common failure causes.~~
3. ~~Add explicit abstention-beat receipts for every Phase 3 selected candidate.~~

### Stage B: estimate better

1. ~~Add Bayesian or empirical-Bayes shrinkage at the slice level.~~
2. ~~Add a search-budget ledger across models, params, symbols, regimes, and execution policies.~~
3. ~~Add drift and change-point state into readiness and demotion logic.~~

### Stage C: allocate better

1. ~~Add robust expected-log-growth optimization with hard reserve cash.~~
2. ~~Add provenance overlap penalties.~~
3. ~~Add capacity curves and marginal-size limits per promoted slice.~~

### Stage D: authorize better

1. ~~Bind canary orders to one-use capability receipts.~~
2. ~~Make live outcomes update evidence only, never direct authority.~~
3. ~~Require fresh re-proof before every scale step.~~

### Stage E: governed multi-system synthesis

1. ~~Inventory the production VNS, CCE, Triune, polyphonic resonance, Seraph, Sophia, and Mandos implementations.~~
2. ~~Define their Hivenance authority boundary as research evidence only, with no execution or promotion authority.~~
3. ~~Add source-fingerprinted lineage receipts for every contributing implementation.~~
4. ~~Add a VNS-derived independent market-observation quality receipt.~~
5. ~~Add polyphonic market voices with mandatory mean-reversion dissent preserved.~~
6. ~~Add CCE-style directional persistence and cross-feature switch analysis.~~
7. ~~Add Triune interpretation, ranking, dissent, and proposal-only adjudication.~~
8. ~~Add Sophia-style adaptive challenge curricula based on reusable slice evidence.~~
9. ~~Add Seraph counterfactual attacks for cost, regime, persistence, discord, and volatility haircut failure.~~
10. ~~Seal each synthesis in a Mandos-style hash-chained decision receipt.~~
11. ~~Register the synthesis as a cold-start Phase 2 challenger that must still settle, calibrate, simulate, and validate.~~
12. ~~Add a fast outcome-blind audit over the latest observation run so proposal and refusal behavior is immediately inspectable.~~

The synthesis is intentionally not a consensus shortcut. Agreement can create a
research proposal; disagreement creates inspectable abstention. Neither outcome
can authorize an order.

### Stage F: Commons evidence throughput

1. ~~Replace Phase 2's newest-25 ticket verification window with exact indexed ticket resolution.~~
2. ~~Preserve expiry, nonce, input-root, signature, local-reproduction, and proposal-only authority checks.~~
3. ~~Apply local model quarantine to wrapped Commons selections and revoke stale-worker adoptions.~~

### Stage G: next profit-conversion program

Struck-through items are now implemented in repo. Unstruck items remain
pending because they require fresh evidence, live account verification, or
human approval.

1. ~~Materialize incremental Phase-2 scorecards and reduce the full acceptance cycle below 60 seconds.~~
2. ~~Add governed hot-store retention and evidence compaction for the 16 GB research database.~~
3. ~~Separate gross signal movement from maker, taker, failed-fill, and chase-policy costs.~~
4. ~~Add and run account-tier Kraken fee verification before treating any simulated edge as executable.~~ Verified `ETH/USD` account-tier fees are now applied to Phase 2 and Phase 3 costing: `maker=40 bps`, `taker=80 bps`.
5. ~~Allocate research by profitability slice and information value rather than model-wide rank.~~
6. ~~Convert synthesis and execution failure causes into prospectively tested negative crystals.~~
7. Require 100 settled forecasts, 24 independent hourly snapshots, positive 1.5x-cost lower bounds, and a positive absolute Phase-4 result before Phase 5 review.
8. Permit only one human-approved USD 5 live canary after every preceding predicate passes.
9. ~~Restore Byron's original CEX multi-horizon market oracle as a Phase-2 research model using Phase-1 observation snapshots across 1h, 5h, 24h, 7d, and 30d contexts where history exists.~~
10. ~~Persist oracle receipts with explicit horizon agreement, weighted move, spread/depth stability, cost hurdle, proposal-only authority, and zero execution authority.~~
11. ~~Merge the repaired-source database-native current-truth reporter, offline pipeline switch, Linux build verifier, and clean release tooling without overwriting newer profit-lab work.~~
12. ~~Add a compact/report-only operational Phase-2 status path so dashboard and operator checks do not trigger full-history scorecard scans.~~
13. ~~Repair the compact Phase-2 SQLite plan by replacing the bad outcome-to-forecast grouped join with bounded primary-key forecast lookups.~~
14. ~~Adapt the Metatron/Michael/Loki triune pattern into each legacy strategy worker as a deterministic research-admission mind.~~
15. ~~Emit Loki challenge and veto receipts for cost domination, regime mismatch, noisy micro-moves, spread traps, stable-pair traps, and negative worker memory.~~
16. ~~Expose triune worker verdict and Loki challenge breakdowns in full and compact Phase-2 scorecards.~~
17. ~~Add a first-class `worker_coalition_meta_v1` Phase-2 model that treats strategy workers as governed voters rather than independent executable strategies.~~
18. ~~Persist exact `hivenance_worker_coalition_receipt_v1` objects with voter lineage, triune assessments, agreement, edge, cost, authority, and zero execution authority.~~
19. ~~Add settlement-only refused-counterfactual coalition forecasts for partial worker agreements that deserve forward evidence without execution authority.~~
20. ~~Adapt the Arda Ainur witness-council pattern into a deterministic `hivenance_meta_strategy_council_v1` for strategy-family routing.~~
21. ~~Specialize worker coalitions by regime lane so trend, breakout, momentum, and mean-reversion families do not vote in one undifferentiated pool.~~
22. ~~Specialize worker coalitions by symbol class so stable pairs, majors, long-tail listings, and high-spread contexts receive different strategy budgets.~~
23. ~~Route Phase-3 execution-lab simulations through coalition-level posterior slices, not only single worker forecasts.~~
24. ~~Convert repeated coalition refusal causes into reusable negative crystals.~~
25. ~~Promote only coalition slices whose settled net-after-cost lower bound beats the primary/federated challengers out of sample.~~
26. ~~Add a BTC/ETH/SOL medium-horizon trend laboratory for `4h`, `6h`, `12h`, and `1d` long/cash-only research.~~
27. ~~Persist exact medium-horizon trend receipts with venue-fee digest, passive/taker policy comparison, buy-and-hold comparison, stressed cost result, and zero execution authority.~~
28. ~~Wire accepted medium-horizon trend receipts into a prospective Phase-2 model that must re-check fresh entry conditions.~~
29. Route active medium-horizon trend forecasts through Phase 3 execution simulation, then Phase 4 adversarial validation, before any Phase 5 shadow review.

Completed Stage-G oracle note:

- Real run `hyp-1785943343193-91d6781b` produced `36` CEX oracle forecasts.
- Oracle non-abstain count was `0/36`; refusals were dominated by horizon
  disagreement, insufficient cost-adjusted edge, and spread instability.
- This is a wiring and falsification improvement, not yet a profit result.

Completed Stage-G triune worker note:

- Individual worker forecasts now carry `hivenance_triune_worker_mind_v1`
  receipts when they have enough signal to matter.
- `worker_coalition_meta_v1` is now registered in Phase 2 as a research-only
  model and can be settled and simulated downstream like other hypotheses.
- The coalition model requires multiple admitted workers, directional agreement,
  cost survival, and explicit proposal-only authority before emitting a
  non-abstain forecast.
- Partial coalitions can now emit settlement-only refused counterfactuals, but
  zero-voter or all-veto slices still abstain.
- The Ainur-derived meta-strategy council now witnesses market cadence,
  measured truth/cost, regime chronology, failure memory, and deep liquidity
  before selecting which strategy families may vote.
- Worker coalitions now carry symbol-class research budgets. Stable,
  high-spread, long-tail, major, core-liquid, hostile, and unknown contexts can
  receive different allowed strategy families, voter thresholds, agreement
  thresholds, and edge-multiple hurdles.
- Phase-3 scorecards now emit coalition execution breakdowns, coalition
  posterior slices, challenger comparisons, and coalition-specific negative
  capability crystals.
- The Phase-3 DIO gate now includes a `coalition_challenger_dominance`
  predicate when coalition slices are present.
- Kraken account-tier fee verification is now binding upstream: Phase 2 uses
  the verified taker fee per side, and Phase 3 uses the verified maker/taker
  schedule and receipt digest before any simulated edge is treated as
  execution-relevant.
- `medium-trend-0a898d58f9aa7578` persisted `72` medium-horizon receipts and
  accepted `2` SOL/USD daily research slices under verified Kraken spot fees.
  These receipts are encouraging because they clear actual fees and 1.5x stress
  accounting in the lab, but they remain research-only until execution,
  validation, and shadow gates accept them.
- `medium_horizon_trend_v1` is now a normal prospective Phase-2 model. It reads
  accepted medium-trend receipts as evidence, re-checks fresh lookback momentum,
  and emits ordinary `hypothesis_forecasts` rows with zero execution authority.
  Its first fresh SOL/USD run abstained because the current entry condition had
  decayed.
- This is the correct direction for profitability: workers become a noisy sensor
  array whose agreement is tested, not a loose collection of tiny trading bots.

## Honest system assessment

As of Wednesday, August 5, 2026:

- Phoenix is already strong as a governed research machine.
- Phoenix is not yet strong as a demonstrated profit machine.
- The next leap will not come from loosening filters.
- The next leap will come from better slice specialization, stronger refusal, better execution-policy matching, and more intelligent capital concentration.

In short:

`more truth before more size`

That is the path that gives Hivenance its best chance of becoming both genuinely clever and genuinely profitable.
