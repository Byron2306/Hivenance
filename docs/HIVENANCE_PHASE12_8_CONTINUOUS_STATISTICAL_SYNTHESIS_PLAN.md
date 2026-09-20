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
