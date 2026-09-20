# Hivenance Phase 12.8 — Continuous Statistical Synthesis

Status: IN PROGRESS
Branch: phase12-learning-causality-audit

## Objective

Turn Hivenance learning from historical lookup into a continuously maintained,
point-in-time-safe probabilistic substrate.

The Queen remains the final research judgment surface. Statistics, Bayesian
state, machine learning, external crypto telemetry, and Crystals are witnesses.
None receives execution or promotion authority from this phase.

## Canonical flow

settled internal outcomes
+ public market observations
+ external crypto statistics
        |
        v
Statistics Bee
        |
        +-- rolling sufficient statistics
        +-- ratios / z-scores / distributions
        +-- calibration / covariance / recency
        +-- strict evidence availability custody
        |
        v
Synthesis Bee
        |
        +-- Bayesian posterior
        +-- hierarchical shrinkage
        +-- uncertainty
        +-- change-point pressure
        +-- regime posterior
        |
        +--------> Learning context
        +--------> Learned Challenger
        +--------> Crystal candidates
        +--------> Queen / WorldGraph

## Authority

Statistics Bee:
- observation-derived research statistics only
- execution_eligible=false
- promotion_eligible=false

Synthesis Bee:
- probabilistic research context only
- execution_eligible=false
- promotion_eligible=false

Learned Challenger:
- may consume synthesis uncertainty and change-point pressure
- synthesis cannot independently increase execution authority
- positive predictive value must be proven prospectively before stronger influence

Queen:
- retains final research judgment
- no Phase 12.8 component may bypass Queen or governance boundaries

## 12.8A — Statistics Bee

Implemented:
- StatisticalEvidence contract
- strict available_at_ms < as_of_ms rule
- rolling sufficient statistics
- n / effective n / wins / losses
- weighted mean / variance / standard deviation
- empirical win rate
- Beta-Binomial posterior win probability
- 90% posterior approximation
- edge-positive probability
- recent-vs-prior change pressure
- evidence root and source ID custody
- WorldGraph/SynthesisRuntime integration

Primary module:
strategies/relative_value_lab/statistical_synthesis.py

## 12.8B — Probabilistic Synthesis

Implemented:
- sparse exact evidence may borrow bounded context from broader scopes
- exact, symbol-class, cohort, and later market-state scopes remain distinguishable
- broader evidence receives specificity weights
- uncertainty rises with scarcity and posterior disagreement
- effective sample size is explicit
- synthesis state is visible to Learning context
- no authority escalation

Primary module:
strategies/relative_value_lab/statistical_synthesis.py

## 12.8C — Bayesian Regime State

Implemented foundation:
- local dependency-light Bayesian regime filter
- states: TREND / MEAN_REVERSION / TRANSITION / STRESS
- explicit transition matrix
- sequential posterior updates
- normalized entropy
- posterior movement / transition mass change-point pressure
- strict point-in-time evidence rule

Primary module:
strategies/relative_value_lab/probabilistic_regime.py

Next:
- derive likelihoods from canonical market sensors
- add volatility state posterior
- compare HMM-style posterior against deterministic regime baseline
- causal ablation against Queen and challenger behavior

## 12.8D — ML Integration

Implemented foundation:
- LearnedChallenger accepts probabilistic synthesis state
- synthesis uncertainty can increase challenger uncertainty pressure
- synthesis change-point probability can increase drift pressure
- bullish posterior cannot automatically increase challenger authority
- missing synthesis state remains explicit

Existing ML ownership remains:
- agents/ml_research_lab.py
- strategies/relative_value_lab/ml_challenger.py
- strategies/relative_value_lab/metatron_ml_challenger.py

Next:
- rolling Brier score
- log loss
- calibration curves
- conformal interval coverage
- feature drift
- label drift
- residual drift
- regime-conditional challenger calibration
- model disagreement as an ablated feature

## 12.8E — External Crypto Statistics Sensorium

Planned first sensor family:
- ETF net flow
- spot CVD
- spot volume
- futures open interest
- funding
- liquidation imbalance
- stablecoin exchange reserve
- BTC/stablecoin reserve ratio
- realized volatility
- options IV and skew
- macro probability state
- BTC-relative breadth

Every external value must be snapshotted on observation with:
- observed_at
- available_at
- provider/source
- original value or bytes digest
- transformation version
- evidence root

Historical APIs that revise past values may not be treated as point-in-time truth
unless Hivenance stored the value itself when originally observed.

## 12.8F — Probability and Ratio Layer

Planned outputs:
- P(edge > 0 after costs | state)
- P(win | state)
- P(drawdown > threshold | state)
- P(volatility expansion | state)
- P(regime transition | state)
- P(liquidation cascade | state)
- P(relative outperformance | state)

Ratios:
- posterior odds
- trend / mean-reversion odds
- OI / spot volume
- ETF flow / spot volume
- stablecoin buying-power ratio
- liquidation long/short ratio
- IV / realized vol
- positive/negative payoff ratio
- weighted support/dissent ratio

## 12.8G — Conformal and Stochastic Uncertainty

Planned:
- online conformal intervals
- rolling empirical coverage
- calibration state: underconfident / calibrated / overconfident
- stochastic volatility posterior
- interval-vs-cost decision context
- uncertainty-aware abstention research

## 12.8H — Crystal Promotion

Crystals remain downstream of Synthesis.

A probabilistic state does not become a Crystal merely because confidence is high.
Crystal candidacy requires:
- recurrence
- transfer testing
- point-in-time custody
- adversarial challenge
- independent-world support
- no future leakage
- explicit applicability
- causal ablation evidence

## Acceptance gates

Phase 12.8 cannot claim useful learning until:

1. Point-in-time invariants pass.
2. Same-time evidence is refused by default.
3. Statistics-to-synthesis behavior is deterministic.
4. Broader evidence does not masquerade as exact evidence.
5. ML authority cannot increase from synthesis alone.
6. Regime posterior is calibrated on held-out/prospective worlds.
7. Conformal coverage is measured prospectively.
8. External telemetry has timestamped custody.
9. Each new organ survives same-world ablation.
10. Prospective shadow evidence demonstrates usefulness after costs.

Execution remains disabled throughout Phase 12.8.


## 12.8I — Canonical ResearchContext Bus

Status: IMPLEMENTING

Purpose:
- replace fragmented side-channel keys with one sealed, point-in-time research context;
- keep compatibility aliases during migration;
- make the same context visible to core hypotheses, strategy workers, ML challengers, and Queen-side cognition.

Canonical sections:
- observed
- regime
- statistics
- learning
- crystals
- external
- calibration
- workers
- provenance

Rules:
- ResearchContext is research-only;
- it may not mutate the observed world;
- all positive authority remains downstream and separately gated;
- legacy feature keys remain adapters only until ablation proves they can be retired.

Primary modules:
- strategies/relative_value_lab/research_context.py
- strategies/relative_value_lab/g0_hypothesis_adapter.py

## 12.8J — Full Organism Topology and Worker Integration

Status: IMPLEMENTING

Strategy Workers:
- retain SMA, RSI, RSI2, Breakout, Momentum, Bollinger, Supertrend, Volatility Expansion and coalition voices;
- workers consume the same ResearchContext as other hypotheses;
- worker receipts preserve the exact context seen;
- workers remain specialist hypothesis voices, not Queen substitutes;
- worker utility must be prosecuted via NO_WORKERS same-world ablation.

Coin Selector:
- remains pre-hypothesis and universe-freezing;
- may consume point-in-time ResearchContext;
- may not rerank after outcome knowledge;
- selection regret remains downstream validation.

Market Hunting:
- remains a research-target generator, never an alpha claim.

Colony Correlation:
- remains discovery-only and may not claim causality.

Causal Cascade:
- remains explicit mechanism-bound propagation analysis.

## 12.8K — Governance and Meta-Cognition Integration

Polyphonic Quorum:
- measures provenance-diverse ensemble health, never directional majority vote.

Pollen Economy:
- remains meta-learning / information-contribution reputation;
- may affect research prioritization;
- may not directly weight trade direction.

Mystique:
- remains synthetic falsification;
- synthetic worlds may never contaminate observed or prospective evidence.

Cognitive Metabolism:
- becomes the information-efficiency and compute-budget governor;
- should terminate recursive cognition when marginal information gain collapses.

VNS / Temporal Texture:
- remains transport/cadence health;
- may influence trust/uncertainty but not originate alpha.

Recursive Queen:
- remains bounded;
- may request refresh/challenge/compare/corroboration;
- may not recurse without explicit stopping conditions.

Conducting Queen:
- remains final research conductor;
- receives structured evidence, uncertainty, dissent and governance state;
- may veto/abstain/request more evidence;
- may not directly bypass execution gates.

Primary topology registry:
- strategies/relative_value_lab/organ_topology.py

## 12.8L — Unified RegimeContext

Status: NEXT

Problem:
- deterministic regime truth currently lives in feature_engine.py;
- Bayesian regime truth currently lives in probabilistic_regime.py;
- consumers may see one or the other through separate channels.

Canonical contract:
- deterministic_hint
- deterministic_confidence
- Bayesian posterior probabilities
- dominant_posterior_regime
- posterior_entropy
- change_point_probability
- disagreement score
- evidence cutoff
- authority and provenance

Influence:
- hypotheses may consume it;
- worker models may consume it;
- ML challenger may consume it;
- Queen may inspect it;
- it may increase caution immediately;
- positive directional weighting requires prospective causal proof.

## 12.8M — Queen Input v2

Status: PLANNED AFTER REGIME CONTEXT

Goal:
- preserve the proven Phase-7 17-channel contract;
- add a versioned extension layer for:
  - STATISTICAL_SYNTHESIS
  - REGIME_CONTEXT
  - EXTERNAL_STATISTICS
  - CALIBRATION_CONTEXT
  - RESEARCH_CONTEXT
- avoid silently changing historical Phase-7 invariants.

The v1 17-channel assembly remains frozen.
Queen Input v2 must be explicitly versioned and backward compatible.

## 12.8N — Full Organism Causal Ablation

Required executable masks, only where real runtime isolation exists:
- FULL_HIVE
- NO_STATISTICS
- NO_BAYES
- NO_REGIME
- NO_EXTERNAL
- NO_CONFORMAL
- NO_ML
- NO_WORKERS
- NO_LEARNING
- NO_CRYSTALS
- NO_COIN_SELECTOR
- NO_QUORUM
- NO_MYSTIQUE
- NO_METABOLISM
- NO_POLLEN
- NO_QUEEN

Each mask must preserve:
- identical observed world;
- identical future settlement tape;
- no synthetic post-hoc mutation of the FULL path;
- separate invocation and influence receipts.

Acceptance:
- invocation is not usefulness;
- decision change is not usefulness;
- positive historical delta is only historical evidence;
- prospective shadow evidence remains required for promotion.

## 12.8O — Information Architecture Optimization

Target architecture:
1. observations create canonical evidence;
2. Statistics Bee accumulates causally available quantitative state;
3. Synthesis Bee creates probabilistic research state;
4. ResearchContext distributes one sealed context packet;
5. specialist organs consume that packet according to their role;
6. Queen receives explicit provenance-bound channels;
7. settlement closes the loop back into statistics/learning/calibration;
8. Crystals remain downstream of recurrence and transfer testing;
9. execution remains downstream of independent promotion/risk gates.

Optimization principles:
- one owner per responsibility;
- one canonical read seam per context family;
- compatibility adapters instead of duplicate truths;
- local/dependency-light computation by default;
- no side-channel may silently acquire authority;
- every meaningful organ must be independently ablatable.


## Implementation checkpoint — Singular Organism Pass

Implemented in the current branch:
- package-edge circular import repaired with lazy volatility_breakout orchestration exports;
- full-organism findings locked into this phase plan;
- canonical ResearchContext implemented;
- canonical RegimeContext implemented and embedded inside ResearchContext;
- deterministic/Bayesian regime disagreement now reduces hypothesis regime confidence;
- strategy worker receipts consume the same canonical regime/context lineage;
- least-privilege ResearchContext router implemented;
- organ-specific context views projected at the common hypothesis adapter;
- Queen Input v2 implemented without mutating the frozen 17-channel v1 contract;
- ConductingQueen receipts now bind Queen Input v2 extension state;
- EXTERNAL_STATISTICS, CALIBRATION_CONTEXT, and ML_CHALLENGER promoted to explicit SynthesisRuntime families;
- NO_BAYES, NO_EXTERNAL, NO_CONFORMAL, and NO_ML added as genuine executable synthesis masks;
- full-organism topology registry defines responsibility, allowed influence, forbidden authority, and disposition.

Next singular-organism tranche:
1. propagate least-privilege ResearchContext views into upper cognition invocation adapters;
2. use Cognitive Metabolism to bound Recursive Queen recurrence by marginal information gain;
3. version and expose explicit Queen v2 extension influence metrics without altering v1 historical receipts;
4. add same-world full-organism causal replay across the expanded mask roster;
5. generate per-organ invocation/influence/economic-value census;
6. retire or quarantine only organs proven redundant, inert, or harmful;
7. keep all positive influence research-only until prospective shadow evidence survives costs.
