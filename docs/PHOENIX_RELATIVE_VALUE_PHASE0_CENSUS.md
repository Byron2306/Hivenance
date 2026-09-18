# Phoenix Relative-Value Laboratory — Phase 0 Census and Disposition

**Status:** implementation census  
**Branch:** `hivenance-phoenix-relative-value-lab`

## Scope

This census identifies existing Hivenance/Phoenix organs that should be reused, extended, or explicitly kept out of the new relative-value path.

## Reuse directly

### Hypothesis competition

- `strategies/volatility_breakout/hypothesis_competition.py`
- `strategies/volatility_breakout/hypothesis_swarm.py`

Disposition: **REUSE**

Reason:
Phoenix already compares frozen hypotheses and baselines on common evidence, persists forecasts, supports abstention, and carries research-only execution flags. Relative-value models should enter as a new hypothesis family rather than bypass this competition.

### Walk-forward calibration

- `strategies/volatility_breakout/walk_forward_calibration.py`

Disposition: **REUSE / EXTEND**

Reason:
Experiment E requires prospective time-shifted labels and walk-forward evaluation. Pair-relative horizons will need their own calibration cohorts but should use the existing calibration philosophy.

### Research federation

- `strategies/volatility_breakout/research_model_federation.py`

Disposition: **REUSE / EXTEND**

Reason:
Existing challenger federation, local-adoption semantics, and transparent model descriptors provide a ready landing zone for relative-value challenger models.

### Forecast object semantics

- `strategies/volatility_breakout/models.py::Forecast`

Disposition: **REUSE CONCEPT / DO NOT OVERLOAD**

Reason:
The existing Forecast object already separates expected move, expected cost, expected net, uncertainty, calibration and abstention. Relative-value forecasts need pair identity and intervals, so the new `ForwardRelativeForecast` contract is separate but semantically compatible.

### Current truth

- `strategies/volatility_breakout/current_truth.py`

Disposition: **REUSE / EXTEND LATER**

Reason:
Relative-value readiness should eventually appear in CURRENT_TRUTH as research capability state, not as live authority.

### Phoenix authority

- `agents/phoenix_authority.py`

Disposition: **REUSE / HARD BOUNDARY**

Reason:
All new organs must remain below Phase 6 live-order authority and Phase 7 scaling authority.

### Negative/positive crystal memory

- Phase 2 crystal context in `hypothesis_swarm.py`
- existing candidate/negative capability semantics

Disposition: **REUSE / SPECIALIZE**

Reason:
A-D failures should become reusable negative capability, especially late-entry, route-cost, mature-streak and chasing failure classes.

### Horizon

- `agents/horizon_context.py`
- `scripts/run_hivenance_horizon_observer.py`

Disposition: **REUSE AS CONTEXT**

Reason:
Horizon provides micro/meso/macro context. It must not become a hidden forecast label or authority source.

### Existing public feed and drizzle labs

- `scripts/run_live_profit_streak_swarm.py`
- `scripts/run_live_relative_drizzle_lab.py`
- `scripts/run_live_inventory_drizzle_lab.py`

Disposition: **REUSE DATA/LESSONS; FREEZE A-D LOGIC**

Reason:
They are valuable controls and historical evidence. Do not mutate them into Experiment E and erase the falsification trail.

## Extend carefully

### Existing FeatureVector

Disposition: **EXTEND THROUGH PAIR-SPECIFIC OBJECTS FIRST**

Reason:
The existing object includes order-flow imbalance, book imbalance, spread, depth, volatility and return features. Pair-relative state should be composed from two symbol observations plus relationship state rather than stuffing all pair semantics into the single-symbol FeatureVector.

### RegimeOracle

- `agents/oracle_regime.py`

Disposition: **REUSE AS ONE REGIME VOICE**

Reason:
Useful context, but pair-specific structural-break and mean-reversion state is distinct from single-symbol market regime.

### Worker coalition / signal federation

Disposition: **CHALLENGER ONLY**

Reason:
A-D showed that worker-derived scoring can amplify recent motion. Worker signals may contribute features/challengers, but cannot define expected future edge without prospective calibration.

### Nurse

Disposition: **REUSE / EXTEND**

Reason:
Nurse should settle pair-forecast outcomes, identify failure classes, and create candidate memories. It must not auto-promote learned rules.

## New organs required

### relative_value_microstructure

Purpose:
public bid/ask, depth, trades, order-flow, intensity, refill/depletion evidence.

Authority:
telemetry only.

### relative_value_pair_lab

Purpose:
pair relationship discovery, spread definition, stationarity/mean-reversion diagnostics, OU-style estimates, half-life, structural breaks.

Authority:
research only.

### relative_value_forecaster

Purpose:
predict future pair-relative returns at 10/30/60/120 seconds using strictly time-shifted labels.

Authority:
research only.

### relative_value_research_council

Purpose:
bounded local Ollama adviser over deterministic evidence packets.

Authority:
advisory only.

### relative_value_graph

Purpose:
represent the basket as a graph of relationship edges and control redundant/common-driver evidence.

Authority:
research only.

### relative_value_execution_lab

Purpose:
paper-only harvesting realism, route/cost/depth/maker/taker counterfactuals.

Authority:
simulation only.

## DIO relationship

DIO currently reuses Hivenance's reasoning architecture and imports bounded Hivenance hypothesis artifacts while explicitly retaining human/operator publication authority in its market lane.

Disposition: **PRESERVE SEPARATION**

Relative-value outputs suitable for DIO:
- hypothesis/evidence receipts
- research current truth
- negative capability
- model disagreement
- world-state-bound forecast evidence

Outputs NOT suitable for DIO as implied authority:
- order intent
- live order
- capital allocation authority
- Phase 6/7 promotion

## A-D evidence disposition

A-D are not failed prototypes to delete. They are the seed negative corpus.

Preserve:
- A weak gross streak vs friction
- B absolute rotation/churn failure
- C full relative-switch failure
- D naive inventory failure
- direct-route advantage
- mature-persistence degradation
- current score miscalibration
- zero-exposure gated variants
- Horizon warmup insufficiency

These become falsification tests for every new model family.

## Phase 0 exit checklist

- [x] new branch created
- [x] master plan recorded
- [x] canonical relative-value research contracts created
- [x] Phoenix authority roles registered
- [x] DIO integration boundary identified
- [x] existing Phoenix hypothesis rails mapped
- [ ] authority/contracts tests passing in repository runtime
- [x] A-D autopsy provenance copied/registered in repo
- [x] Phase 1 microstructure evidence schema frozen
