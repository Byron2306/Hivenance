# HiveNance Phoenix Deep Organism Census

Date: 2026-09-19  
Branch: `hivenance-phoenix-edge-ecology`  
Status: architecture/causal census, research-only

## Executive finding

HiveNance is not one coherent prediction pipeline. It currently contains several substantial, partially overlapping nervous systems:

1. the legacy Coordinator / strategy-worker / Council / RegimeOracle / Queen / SwarmGuard path;
2. the Phoenix Observation -> Hypothesis Competition -> validation/shadow/canary research path;
3. the relative-value polyphonic / Queen / Pollen / quorum path;
4. the newer Horizon micro/meso/macro observer;
5. the newer Edge Ecology microstructure experiment.

Many organs are real and non-trivial, but "implemented" does not mean "causally active in the experiment currently being run". The main architectural defect is fragmentation of evidence and authority between these paths.

The immediate priority is therefore not another indicator. It is a causal wiring audit and controlled ablation programme that proves which organs alter forecasts, selection, abstention, and prospective post-cost outcome.

## 1. Canonical organism map

### A. Public perception and candidate discovery

Primary components:
- `agents/kraken_public_rest.py`
- `agents/market_data.py`
- `agents/coin_selector.py`
- `strategies/volatility_breakout/observation_swarm.py`

Phoenix Observation constructs public-market candidate state and feature vectors. Its features include price/volume, volatility, spread/depth, order-flow/book imbalance when available, returns, trend/reversal descriptors, data quality and regime inputs. Observation is the principal Phase-1 research ingress.

Authority: observation/research only.

### B. Legacy multi-timeframe regime cognition

Primary component:
- `agents/oracle_regime.py`

`RegimeOracle` is a genuine multi-timeframe organ, defaulting to 1m/5m/1h. It computes trend strength/direction, volatility, mean crossing, Bollinger width, wick/spike behaviour, volume/volume expansion, short return, drawdown and spread. It classifies regimes including TREND_UP, TREND_DOWN, CHOP_RANGE, BREAKOUT, VOL_EXPANSION, PUMP, DUMP, PANIC_VOLATILE and LOW_LIQUIDITY, with confirmation and minimum-duration hysteresis.

It is instantiated by the legacy Coordinator and its regime snapshot affects Council alignment, Queen SVS regime fit and SwarmGuard regime gates.

Critical distinction: this proves RegimeOracle is active in the legacy Coordinator path. It does not prove that its exact snapshot is an input to every Phoenix Phase-2 hypothesis or the Edge Ecology experiment.

### C. Legacy strategy-worker nervous system

Primary components:
- `agents/strategy_workers.py`
- `agents/council.py`
- `agents/queen.py`
- `agents/swarmguard.py`
- `agents/coordinator.py`

Workers generate BUY/SELL/HOLD proposals. Council aggregates active proposals with regime alignment and worker performance weights. Queen independently scores proposals using regime fit, performance, signal quality, execution friction and risk. SwarmGuard applies liquidity caps, spread/fee vetoes, rate limits, consensus/diversity requirements, regime vetoes and rulebook controls.

The existing `STRATEGY_WORKER_AUDIT.json` explicitly records that legacy workers do not have direct Phase-2 authority. They are council-era signal workers; Phase-2 primarily consumes native/federated research models. Worker ideas can re-enter Phase-2 through worker-signal federation / coalition models, which is a different path from the live legacy Council.

### D. Phoenix Hypothesis Swarm

Primary components:
- `strategies/volatility_breakout/hypothesis_swarm.py`
- `strategies/volatility_breakout/hypothesis_competition.py`
- `strategies/volatility_breakout/hypothesis_models.py`
- research-model federation, worker-signal federation and coalition modules
- walk-forward calibration and research-reuse governor

This is a much richer research organ than a simple hypothesis generator.

For each Observation candidate, HypothesisSwarm can add:
- profitability-frontier context;
- regime-suppression context;
- worker-signal memory;
- CEX market-oracle context;
- medium-horizon trend context;
- derivatives-trend context;
- positive thesis-crystal memory;
- negative-crystal memory.

HypothesisCompetition then evaluates primary models, federated models, worker-derived models and explicit baselines under the same feature state. It includes breakout and exhaustion/reversion hypotheses plus no-trade, momentum, mean-reversion and deterministic-random baselines.

Important: medium-horizon and derivatives-trend models are real code paths. They are not merely documentation.

All Phase-2 forecasts are research-only and are explicitly checked against acquiring execution eligibility.

### E. Crystal memory

HypothesisSwarm reads positive and negative crystal context and writes `phase2_crystal_memory` into the feature values. Support/warning scores can alter research-route priority. Non-abstaining forecasts can subsequently be persisted as thesis-capability crystal entries.

This forms a feedback loop:

forecast -> settlement/evidence -> crystal memory -> later hypothesis context

However, priority adjustment is not equivalent to demonstrated economic benefit. Crystal memory needs a prospective ablation: same candidate stream with crystal context ON versus OFF.

### F. Medium/long horizon cognition already exists twice

There are two separate implementations.

1. `RegimeOracle`: 1m/5m/1h OHLCV regime classification inside the legacy Coordinator path.
2. `agents/horizon_context.py` + `scripts/run_hivenance_horizon_observer.py`: a newer public research observer covering micro 10s/30s, meso 2m/5m, macro 15m/1h plus Kraken 24h ticker context, cross-sectional relative strength, alignment and regime hints.

The Horizon observer persists its own SQLite database and can restore local history across runs. It monitors multiple symbols and calculates market breadth and relative leaders.

This means the proposed "Temporal Ecology" is substantially already implemented as Horizon Context. The problem is not absence of temporal perception. The unresolved question is whether Horizon Context is wired into the Edge Ecology / Phoenix hypothesis decision path.

### G. Polyphonic relative-value cognition

Primary components include:
- `strategies/relative_value_lab/polyphonic_quorum.py`
- conducting Queen / temporal texture / motif / harmonic modules
- Pollen economy and `pollen_profit_lab.py`

This path models role-diverse evidence, lineage independence, evidence diversity, counterpoint and quorum. Quorum means synchronized, sufficiently independent evidence choreography, not directional agreement.

Pollen is a research-attention economy. Queen notation can issue bounded bounties for dissent, corroboration, novelty, search, settlement and efficiency. Pollen and quorum have no execution/promotion authority.

Existing prospective ablation evidence showed some of this machinery did not alter selection in the measured sample. That is a causal result, not a reason to delete the organs blindly. It means their current wiring/thresholds did not change decisions in that sample.

### H. Edge Ecology

Primary components:
- `strategies/relative_value_lab/edge_ecology.py`
- `strategies/relative_value_lab/metatron_ml_challenger.py`
- `scripts/run_edge_ecology_experiment.py`

The current V2 experiment observes one Kraken spot symbol at high cadence and tests flow exhaustion/persistence, liquidity, short trend and an ML anomaly challenger at 15/30/60/120-second settlement horizons.

It is deliberately isolated and research-only.

Critical architectural limitation: it does not currently consume the full HypothesisSwarm, RegimeOracle, Horizon Context, crystal-memory, Queen/Pollen or legacy Council state. It is therefore an experiment beside HiveNance, not yet a unified expression of the organism.

## 2. What is actually active versus merely present

### Proven active by direct call path
- Kraken public observation in the research experiments.
- ObservationSwarm -> HypothesisSwarm.
- HypothesisSwarm -> HypothesisCompetition.
- HypothesisCompetition primary/baseline/federated model routing.
- HypothesisSwarm enrichment hooks for frontier, suppression, worker memory, CEX oracle, medium trend, derivatives trend and crystal memory.
- RegimeOracle -> legacy Coordinator/Council/Queen/SwarmGuard path.
- Edge Ecology flow/liquidity/trend/ML -> V2 settlement books.
- Horizon observer -> its own SQLite context store.

### Implemented, but economic contribution not established
- crystal-memory priority adjustment;
- worker-signal federation and coalition;
- medium-horizon trend forecasts;
- derivatives-trend forecasts;
- Commons challenger inference;
- RegimeOracle's net contribution versus simpler controls;
- Queen/Council/SwarmGuard contribution to post-cost outcome;
- polyphonic quorum and Pollen economics.

### Demonstrated weak/dead in at least one prior prospective sample
The earlier Pollen ablation found zero selection effect for pollen bounties, quorum gate and reputation in that sample, while counterpoint hold, motion voice and Queen resolution changed selection. This is sample-specific evidence, not a universal verdict.

### Clearly disconnected from the current Edge Ecology V2 experiment
- RegimeOracle;
- legacy Council and GovernanceQueen;
- SwarmGuard;
- HypothesisSwarm/HypothesisCompetition;
- thesis-crystal memory;
- Horizon Context;
- polyphonic/Pollen machinery.

That disconnection is the central finding of this census.

## 3. Current scientific truth

The repository's `CURRENT_TRUTH.json` states research-only authority, no demonstrated durable post-cost edge and no live execution authorization. That remains the correct boundary.

The latest Edge Ecology hour is exploratory evidence, not promotion evidence. Its 60-second reversion selector was positive gross in a tiny selected sample, while broad reversion was also positive. This motivates mechanism testing, not tuning to the winning horizon.

## 4. Architectural diagnosis

HiveNance has accumulated capable organs faster than it has accumulated causal integration tests.

The architecture has three recurring failure modes:

1. **Parallel nervous systems**: legacy Council/Oracle, Phoenix hypothesis research, relative-value polyphony, Horizon and Edge Ecology can each reason about the market without a single canonical world-state contract.
2. **Presence mistaken for influence**: an organ may be instantiated, persist receipts or appear in UI while having zero marginal effect on selection.
3. **Evidence feedback without proven utility**: crystals, reputation, Pollen and learned suppression can feed later research, but their existence does not establish that the feedback improves prospective net outcome.

## 5. Required repair programme

Do not add another prediction organ until this is complete.

### Census Gate A: canonical world-state map
For every market fact, record producer, schema, cadence, persistence, consumers and authority. Reconcile Observation feature vectors, RegimeOracle snapshots, Horizon Context and Edge Ecology state.

### Census Gate B: call-graph truth
Instrument one candidate from public ingress through every participating organ. Emit a trace receipt containing every organ invoked, every input digest, every output digest, and whether that output changed the eventual forecast/abstention.

### Census Gate C: marginal-effect ledger
For each organ, record:
- invoked count;
- non-default output count;
- decision-change count;
- selection-change count;
- direction-change count;
- abstention-change count;
- settled delta versus paired control;
- sample size and uncertainty.

An organ with 10,000 invocations and zero decision changes is observational, not causally active.

### Census Gate D: controlled organ ablations
Run paired prospective books:
- full organism;
- minus RegimeOracle;
- minus Horizon Context;
- minus crystal memory;
- minus worker memory;
- minus medium trend;
- minus liquidity;
- minus ML veto;
- minus Queen/counterpoint;
- minus Pollen/quorum;
- deterministic matched control.

Do not optimize thresholds during this experiment.

### Census Gate E: nervous-system consolidation
Only after Gate D, define one canonical research flow. Candidate proposal:

public market -> canonical world-state crystal -> horizon/regime context -> independent hypothesis voices -> hypothesis competition -> Queen/counterpoint resolution -> cost/quality gate -> prospective paper settlement -> evidence/crystal update.

Legacy execution governance remains outside this research authority until post-cost evidence earns a later gate.

## 6. Immediate conclusion

The earlier assumption that HiveNance lacked multi-horizon cognition was wrong. It already has substantial multi-horizon machinery, including a dedicated Horizon Context observer that almost exactly matches the proposed Temporal Ecology concept.

The actual defect is more important: those capabilities are fragmented across different pipelines and are not yet proven to influence the same decisions.

The next engineering work should therefore be a causal integration/audit harness, not another strategy. Its first job is to answer, with receipts rather than architecture diagrams:

**For this exact forecast, which HiveNance organs actually changed the decision, and did that change improve the prospective outcome?**
