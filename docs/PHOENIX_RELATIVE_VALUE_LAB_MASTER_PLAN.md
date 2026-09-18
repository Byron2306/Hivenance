# Phoenix Relative-Value Laboratory Master Plan

**Branch:** `hivenance-phoenix-relative-value-lab`  
**Status:** Phase 0 in progress  
**Programme objective:** turn Phoenix from a short-horizon motion scorer into a scientific, forecast-first relative-value research organism for high-volatility, low-stakes "drizzle" strategies.

## Why this programme exists

Experiments A-D established that the current drizzle implementations are not economically supported.

The key failure was not simply fees. The current edge formulation mostly transformed recent motion into a score and was negatively related to future 30-second relative capture in Experiment D. Mature streak persistence was also associated with worse subsequent outcomes. Direct pair routes materially reduced cost, but did not rescue the signal.

The next programme therefore changes the scientific target:

```text
current/past evidence
        ->
forecast future pair-relative return distribution
        ->
estimate execution cost and uncertainty
        ->
abstain unless forecast surplus survives
        ->
paper-only inventory experiment
        ->
settled evidence
```

No live authority is created by this programme.

## Existing Phoenix rails to reuse

This programme MUST reuse, not bypass:

- `strategies/volatility_breakout/hypothesis_swarm.py`
- `strategies/volatility_breakout/hypothesis_competition.py`
- `strategies/volatility_breakout/research_model_federation.py`
- `strategies/volatility_breakout/walk_forward_calibration.py`
- `strategies/volatility_breakout/current_truth.py`
- `agents/phoenix_authority.py`
- Phase 3 execution lab
- Phase 4 adversarial validation
- Phase 5 shadow governance
- Phase 6 sole live-order authority
- Phase 7 sole scaling authority

The new relative-value laboratory enters Phoenix at Phase 2 as research evidence and challenger forecasts. It cannot skip Phase 3-5.

## DIO integration contract

DIO already imports bounded Hivenance hypotheses and reuses Hivenance's reasoning architecture without importing its execution authority.

This programme therefore exposes DIO-safe artifacts:

- pair-state receipts
- forecast receipts
- hypothesis receipts
- settled-outcome receipts
- negative-capability receipts
- research-council receipts
- current-truth summaries

DIO may consume these as evidence or bounded hypotheses. DIO must not infer live trading authority from them.

## Scientific object model

### Pair Relationship Crystal

A bounded statement about whether two assets currently form a meaningful relative-value research pair.

Fields include:

- pair id
- venue
- direct-route availability
- relationship method
- lookback
- correlation
- hedge ratio
- spread definition
- stationarity diagnostics
- mean-reversion estimate
- half-life
- structural-break state
- stability score
- freshness
- evidence root
- authority = research_only

### Relative Market State

Current pair state:

- spread
- spread z-score
- relative return horizons
- realized relative volatility
- drawdown/excursion
- microstructure state
- order-flow imbalance
- aggressor-flow intensity
- depth recovery/depletion
- Horizon micro/meso/macro context
- route and cost state

### Forward Relative Forecast

The central object of the programme.

Targets:

- +10s pair-relative return
- +30s
- +60s
- +120s

Fields:

- expected gross move bps
- prediction interval
- probability positive gross
- expected execution cost
- expected net move
- uncertainty
- calibration state
- abstention reasons
- model lineage
- feature digest
- execution_eligible = false

### Research Council Receipt

Local Ollama can consume deterministic model outputs and return:

- contradictions
- missing evidence
- alternative hypotheses
- regime anomalies
- suggested experiments
- model disagreement explanations

It may NOT emit executable intents or promotion decisions.

## Phase sequence

### Phase 0 - Census, contracts and authority freeze

Goal:
- inventory existing Phoenix hypothesis, forecasting, cost, microstructure, learning and authority organs;
- bind the A-D statistical autopsy into programme provenance;
- define new relative-value schemas;
- register new components with Phoenix authority.

Exit:
- canonical architecture map exists;
- authority tests prove no new live path;
- DIO evidence boundary documented;
- all new objects are research-only.

### Phase 1 - Public microstructure evidence fabric

Goal:
collect better public evidence instead of only last-price motion.

Add:
- bid/ask
- spread
- top-of-book depth
- depth at configured bps bands
- trade prints
- aggressor-side proxy when venue data permits
- order-flow imbalance
- trade intensity
- refill/depletion metrics
- route graph and direct-pair map
- data-quality/freshness receipts

Exit:
- timestamped public microstructure snapshots persist;
- gaps are explicit;
- no private API required;
- no orders.

### Phase 2 - Pair Laboratory

Goal:
discover which relationships are scientifically suitable for relative-value research.

Models:
- return correlation as diagnostic only;
- rolling hedge-ratio regression;
- spread construction;
- stationarity diagnostics;
- mean-reversion speed;
- Ornstein-Uhlenbeck-style parameter estimation;
- half-life;
- structural-break/change-point state;
- rolling stability score;
- pair graph across the selected basket.

Important:
cointegration/stationarity is a filter, not proof of profitability.

Exit:
- every candidate pair has a Pair Relationship Crystal;
- unstable pairs abstain;
- direct-route and cost metadata bound.

### Phase 3 - Forward Forecast Engine

Goal:
replace hand-built "edge now" scores with explicitly time-shifted predictions of future pair-relative return.

Targets:
- 10s / 30s / 60s / 120s future relative return.

Candidate model families:
- deterministic baselines;
- regularized linear models;
- mean-reversion/OU forecast;
- regime-conditioned models;
- simple tree/boosting candidate if dependencies permit;
- worker coalition challenger;
- federated research challengers.

Features may include:
- spread z
- distance from equilibrium
- estimated half-life
- relative velocity
- acceleration/deceleration
- realized relative volatility
- order-flow imbalance
- aggressor-flow delta
- depth recovery
- spread/depth cost
- Horizon state
- worker disagreement

Rules:
- strict time shift;
- no random train/test shuffle;
- walk-forward only;
- calibration by horizon;
- predictions settle against later observed data.

Exit:
- out-of-sample forecast skill is measurable;
- forecast calibration receipts exist;
- current-motion score is no longer called edge.

### Phase 4 - Exhaustion and reversal research

Goal:
test the strongest revised drizzle hypothesis:

`stable relative relationship + extreme excursion + flow exhaustion + forecasted reversion`

Research triggers:
- statistically meaningful spread excursion;
- relationship still valid;
- aggressive flow decelerating or flipping;
- depth stabilizing/recovering;
- future-return forecast positive enough to survive cost;
- direct route preferred.

Controls:
- excursion only;
- flow exhaustion only;
- OU only;
- forecast only;
- random matched-entry;
- no-trade.

Exit:
- event studies show whether exhaustion adds predictive information after multiple-testing correction.

### Phase 5 - Local Phoenix Quant Researcher

Goal:
add Ollama as a bounded advisory organ.

Input:
structured deterministic evidence packet only.

Output:
- contradiction list
- missing evidence
- alternative explanations
- analogous historical slices
- suggested falsification tests
- confidence in explanation, not trade

Forbidden:
- BUY/SELL execution command
- authority mutation
- threshold auto-edit
- candidate promotion

Implementation:
- local Ollama endpoint;
- structured JSON schema;
- timeout/failure = deterministic pipeline continues;
- model output stored as untrusted advisory evidence;
- optional independent re-ask / challenge.

Exit:
- inference is reproducible enough to audit;
- offline failure does not impair deterministic models;
- authority guard tests pass.

### Phase 6 - Relative-Value Graph and "elastic bands"

Goal:
treat the basket as a graph of pair relationships.

For N assets, evaluate N*(N-1)/2 unique relationships.

Each edge carries:
- stability
- spread state
- half-life
- forecast
- cost
- flow state
- uncertainty

Research:
- rank local dislocations;
- prevent highly redundant pair bets;
- detect common-driver moves;
- explore triangular inconsistency as research-only anomaly evidence.

Triangular relative-value ideas are exploratory and must not become an execution shortcut.

Exit:
- graph can identify the strongest research dislocations without double-counting correlated edges.

### Phase 7 - Execution-realism laboratory

Goal:
test whether a forecastable relative move can actually be harvested.

Paper-only policies:
- tiny inventory tilt;
- direct-pair first;
- routed fallback as separate cohort;
- taker model;
- maker counterfactual;
- passive-quote research model;
- depth-aware size;
- latency/slippage sensitivity.

Primary comparison:
net settled capture versus equal-weight hold / no-trade / matched random controls.

Exit:
- gross signal and execution drag are separately identifiable;
- no claims are made from cost-free backtests.

### Phase 8 - Adversarial validation and prospective Experiment E

Goal:
freeze the selected research hypothesis and face unseen public market data.

Requirements:
- parameter freeze;
- feature freeze;
- pair-selection freeze;
- walk-forward calibration;
- block-bootstrap uncertainty;
- first/second-half stability;
- leave-one-symbol/pair-out sensitivity;
- direct/routed cohorts;
- multiple-comparison control;
- negative-case replay.

Verdicts:
- NOT_SUPPORTED
- PROMISING_BUT_UNPROVEN
- SUPPORTED_AS_RESEARCH_HYPOTHESIS

Even SUPPORTED_AS_RESEARCH_HYPOTHESIS does not grant live authority.

## Initial Experiment E hypothesis

> A small relative-value inventory tilt can produce positive post-cost expected value only when a pair relationship is demonstrably stable, its relative spread is unusually displaced, order-flow pressure causing the displacement is exhausting, and an independently calibrated forward model predicts reversion large enough to clear direct execution friction with a safety margin.

This is deliberately narrower than A-D.

## Statistical rules

- prospective labels only;
- walk-forward splits;
- no random leakage;
- event-level block bootstrap;
- confidence intervals before point-estimate celebration;
- BH-FDR on exploratory subgroup tests;
- retain negative results;
- no same-run threshold tuning can count as validation;
- abstention is always a first-class baseline;
- DIO/Hivenance crystals preserve failures as reusable negative capability.

## Local-first policy

Preferred stack:

- Python
- SQLite
- NumPy/SciPy/statsmodels when already available or deliberately added
- local Ollama only for advisory inference
- no cloud LLM requirement
- public market data only for the research programme

The deterministic pipeline must remain fully usable if Ollama is unavailable.

## Programme success

The programme succeeds scientifically even if the final trading hypothesis is rejected.

A successful outcome is one of:

1. reliable out-of-sample post-cost relative-return skill is found and survives prospective validation; or
2. the hypothesis is falsified with enough precision to stop wasting search budget and redirect Phoenix.

The programme must prefer a truthful REFUSE over manufactured edge.

---

## Polyphonic Cognition Fabric expansion

The relative-value laboratory is now the first proving ground for the canonical
HiveNance Polyphonic Cognition Fabric:

`docs/HIVENANCE_POLYPHONIC_COGNITION_FABRIC.md`

This expansion adds governed research phases for:

- Waggle Protocol and lineage identity;
- hypothesis accumulation;
- proactive Market Hunting;
- Colony Correlation;
- causal Cascade and Hive Pulse;
- Polyphonic Resonance;
- Harmonic Governance;
- Mystique counterfactual falsification;
- cognitive metabolism (CBR/TBCR/CDI);
- learned ML challengers;
- VNS-bound canonical Phoenix World State;
- Triune synthesis / validation / dissent;
- research Outbound Gate.

Threat-hunting, correlation and ML patterns are adapted from Metatron as research
architecture only. Cybersecurity-specific semantics are not copied into market
truth. Synthetic model data may test plumbing but cannot establish market edge.

All new cognition organs remain bound by:

`research_evidence_only_no_execution_or_promotion_authority`

The entire organism must be frozen before the next fresh prospective validation
window.
