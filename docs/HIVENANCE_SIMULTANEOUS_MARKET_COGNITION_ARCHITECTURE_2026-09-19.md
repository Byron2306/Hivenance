# HiveNance Simultaneous Market Cognition Architecture

Status: research architecture proposal. Public-market research only. No execution or promotion authority.

## Core distinction

A Bee is a specialist observer/explainer. It owns one evidence family, produces timestamped claims with provenance, confidence, freshness and abstention, and never owns a trade.

A Worker is a strategy/proposal engine. It consumes a world-state page and Bee claims to propose a falsifiable action hypothesis.

The Queen resolves evidence and disagreement. She does not manufacture missing evidence or convert consensus into truth.

## Evidence Bee colony

- Temporal Participation Bee: UTC hour/day, weekend, session overlap, activity normalized for that hour.
- Flow Bee: aggressive flow, intensity, persistence/deceleration, absorption.
- Liquidity Bee: spread, depth, imbalance, replenishment, impact/recovery.
- Derivatives/Carry Bee: funding, basis, open interest, liquidations when public data exists.
- Cross-Market Bee: breadth, dispersion, correlation, beta, leader/laggard, relative strength.
- Volatility Bee: realized volatility, vol-of-vol, compression/expansion, jump state.
- Information Arrival Bee: scheduled macro/market events and public crypto events with strict event-time provenance.
- Path Geometry Bee: path efficiency, acceleration, drawdown, VWAP/local-extreme distance.
- On-chain/Capital Bee: slower-horizon exchange, stablecoin and network flows with explicit latency.

Existing Horizon and RegimeOracle remain higher-order context organs, not duplicates. Crystals are memory/authority objects, not observers. ML remains a challenger Bee/model, not the Queen.

## One timestamp, one World State Page

At decision timestamp T, Market Memory freezes an immutable page containing raw facts available by T, Bee evidence, Horizon/Regime context, CoinSelector selected and rejected universe, worker/crystal context, and freshness/missing-data masks.

Every organ receives the same world_state_id. No organ may silently fetch later data. This creates semantic simultaneity without pretending all computation occurs at the same CPU instant.

## Three synchronized cognition lanes

OBSERVE: Bees continuously append independent evidence to Market Memory.

COMPARE: a Comparison Engine continuously builds contrasts: coin vs its normal state for the same UTC interval; selected vs rejected; coin vs market basket; current vs comparable regimes; conflict vs non-conflict; event vs matched non-event; Bee-present vs Bee-absent; actual hypothesis vs random/no-trade/time-shift controls.

HYPOTHESIZE: Hypothesis Bees and Workers consume the frozen page plus comparisons and emit small falsifiable claims. The page may contain hundreds of observations, but a hypothesis should name only a few variables.

The three lanes rendezvous in a Hypothesis Envelope keyed by world_state_id.

## Challenge, resolve, settle

Counterpoint must search for contradictory evidence, nearest historical failures, leakage/staleness, redundant variables, simpler explanations and placebo/random controls.

Queen resolution is typed: ADMIT_FOR_OBSERVATION, HOLD_FOR_MORE_EVIDENCE, REJECT_REDUNDANT, REJECT_CONTRADICTED, REJECT_STALE, or REJECT_LEAKAGE_RISK.

Admission never means profitable or executable. Every admitted and rejected candidate is settled at preregistered horizons. Rejected coins and hypotheses remain in memory so selection regret is measurable.

## Comparison is first-class cognition

Comparison happens before resolution, not as a report after prediction. Each claim should carry self-baseline, cross-sectional, regime, counterfactual and control references where possible. The Comparison Engine produces evidence, never a trade direction.

## Prevent feature explosion

Broad memory, narrow experiments.

1. Store broad timestamp-correct public evidence.
2. Hypotheses declare variables before evaluation.
3. Default to only a small number of explanatory variables per hypothesis.
4. New interactions are explicit hypotheses, not silently generated features.
5. Thresholds discovered on an evaluation slice cannot be promoted on that slice.
6. Missingness is explicit; no hidden forward fill.
7. Derived features record source timestamps and transformation version.
8. Correlated Bees do not count as independent quorum evidence merely because they have different names.
9. Complexity must beat a simpler nested hypothesis.
10. Historical discovery, held-out validation and prospective evidence remain separate authority classes.

## Causal organ ledger

Each organ progresses only through AVAILABLE -> INVOKED -> INFLUENTIAL -> HISTORICALLY_USEFUL -> PROSPECTIVELY_USEFUL.

Measure whether it changed admission/direction/ranking, incremental information over baseline, organ removal, shuffled-organ placebo, rejected-candidate outcomes, post-cost economics and symbol/time/regime holdouts. No Bee gets credit merely for agreeing with a winner.

## Implementation sequence

MCP-1: Common BeeEvidence schema and registry.
MCP-2: Temporal Participation Bee, starting with UTC topology and hour-normalized activity rather than nationality assumptions.
MCP-3: Comparison Engine keyed to world_state_id.
MCP-4: Adapt existing Flow/Liquidity/Volatility voices into BeeEvidence instead of duplicating them.
MCP-5: Derivatives, Cross-Market and Path Geometry Bees.
MCP-6: Blind organ examinations for Horizon, RegimeOracle, Bees, Workers, crystals, Counterpoint, Queen/Pollen.
MCP-7: Hypothesis Envelope plus causal receipts showing exactly which evidence changed what.
MCP-8: Freeze survivors and begin prospective shadow observation. Execution stays locked.

## Target flow

PUBLIC FACTS -> MARKET MEMORY -> EVIDENCE BEES + HORIZON/REGIME + COMPARISON ENGINE + COIN SELECTOR -> WORLD STATE PAGE @ T -> HYPOTHESIS BEES + STRATEGY WORKERS -> HYPOTHESIS ENVELOPE -> COUNTERPOINT/VNS -> QUEEN -> ADMIT/HOLD/REJECT -> SETTLE -> CAUSAL/COUNTERFACTUAL RECEIPT -> LEARNING LEDGER -> crystals/reputation, never direct authority.

## North-star question

HiveNance should not ask only "what happens next?"

It should ask: "What world are we in, what changed, compared with what, which explanations survive contradiction, and what did each organ actually contribute?"

That is the synthesis: broad perception, simultaneous comparison, narrow hypotheses, adversarial resolution and evidence that accumulates without silently becoming authority.
