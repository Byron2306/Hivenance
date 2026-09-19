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


## Queen correction: Conductor, Triune Mind, and Epoch authority

The Queen is not merely the final resolver in this architecture. She is the conductor of the polyphonic research organism.

Her Triune Mind remains explicit:
- **Metatron** synthesizes the composition: what voices are present, how evidence relates, where motifs repeat, and what the current score is trying to express.
- **Michael** guards tuning, provenance, epoch discipline and world-state binding: whether the ensemble is playing the right score at the right time with admissible evidence.
- **Loki** supplies adversarial counterpoint: contradiction, false-unison detection, alternative explanations and pressure against premature harmony.

The Queen conducts rather than majority-votes. Existing polyphonic quorum semantics already model WAGGLE/SEARCH as CALL, FOLLOW as RESPONSE, DISSENT/ALARM as COUNTERPOINT, and ABANDON/SETTLE as RESOLUTION. Quorum therefore means synchronized, independently rooted choreography, not agreement.

### Waggle / notation loop

The Queen publishes bounded notation to the colony. Notation can request challenge cadence, independent corroboration, fresh timbre, search amplification, modulation/temporal/propagation traces, edge-resolution rehearsal, open coda or thinner orchestration. The existing QueenPollenConductor can translate these score tokens into bounded Pollen research bounties.

Evidence Bees do not simply push everything upward. They listen for the current score and answer with independent evidence. The Queen may intensify, thin, redirect or hold the orchestration while preserving dissent.

### Epoch changes

An epoch is the Queen's research-attention regime, not a trading permission.

An epoch change may alter:
- which evidence families receive attention;
- cadence and sampling density;
- which comparisons are requested;
- which hypotheses are invited to challenge or corroborate;
- how much independent evidence is required;
- which historical analogues are rehearsed;
- whether the score is exploring, challenging, settling or observing.

An epoch change must never rewrite historical evidence, expose future information, promote a hypothesis, or authorize execution. It changes the **questions and choreography**, not truth.

Proposed typed epochs:
1. LISTEN: broad sensing, low commitment.
2. SEARCH: Queen issues waggle/search calls for missing or novel evidence.
3. CHALLENGE: Loki/counterpoint/VNS pressure dominant explanations.
4. CORROBORATE: Michael demands independent roots, provenance and world binding.
5. REHEARSE: compare candidate explanations against historical analogues and controls.
6. OBSERVE: freeze admitted hypotheses for prospective shadow observation.
7. SETTLE: close matured forecasts and update causal ledgers.
8. RETUNE: detected drift/decay causes notation and attention to change without erasing prior knowledge.

Transitions must be receipt-bound and explainable: prior_epoch, next_epoch, trigger evidence, Triune votes/roles, notation issued, world_state_id and authority boundary.

### Harmonic governance

Harmonic governance belongs between evidence production and Queen notation. It measures ensemble properties such as cadence, drift, jitter, burstiness, entropy, resonance/discord and confidence. It is descriptive pressure, not truth and not execution authority.

Its job is to tell the Queen whether the colony is:
- in healthy independent harmony;
- preserving useful counterpoint;
- drifting out of phase;
- exhibiting duplicated evidence / false unison;
- becoming overconfident;
- missing an expected voice;
- changing faster than the current epoch can safely interpret.

The Queen can then change the waggle, cadence or epoch.

## Revised simultaneous cognition loop

The system is not a simple linear pipeline. It is a conducted recurrent loop:

PUBLIC FACTS -> MARKET MEMORY -> Evidence Bees / Horizon / Regime / Comparison -> WORLD STATE PAGE.

The Queen's current epoch and notation simultaneously influence what the colony inspects next. Evidence and comparisons return as polyphonic notes. Triune cognition synthesizes, validates and attacks the score. Harmonic governance measures ensemble health. Quorum checks synchronized independent choreography. The Queen then changes notation, requests new Bee work, changes epoch, admits/holds/rejects a research hypothesis, or waits.

Workers remain proposal/strategy engines inside this conducted loop. They do not replace Bees, and Bees do not become Workers.

Phoenix remains the canonical experiment authority: hypothesis identity, freeze, prospective forecast, settlement, ablation and promotion evidence. The Queen conducts **which research should happen next**; Phoenix ensures that the research cannot quietly move its goalposts.

## Full synthesis programme

### Phase S0: Preserve and census
Freeze current historical evidence and current positive/negative findings. Inventory Queen notation, Triune semantics, VNS/TRY reasoning, harmonic inputs, Pollen, quorum, Horizon, RegimeOracle, workers, crystals, Edge voices and Phoenix authority. Produce responsibility/overlap map before rewiring.

### Phase S1: Common Evidence Contract
Implement BeeEvidence with world_state_id, family, claim, value/features, observed_at, source timestamps, freshness, lineage/evidence roots, confidence, abstention, authority and transformation version. Add registry and deterministic receipts.

### Phase S2: Temporal Participation Bee
Build the first new Bee from Market Memory: 24-hour UTC topology, weekday/weekend, broad session overlap labels, and actual activity normalized against the same UTC interval. Test all 24 hours before any interval optimization. Bind to the frozen 1h-vs-24h mechanism as a descriptive challenge, not a promoted filter.

### Phase S3: Comparison Engine
Make comparison simultaneous and first-class: self-at-same-hour, cross-sectional peers, selected/rejected, nearest prior world states, conflict/non-conflict, event/matched non-event, random/no-trade/time-shift controls. Every comparison is timestamp-safe and world-bound.

### Phase S4: Adapt existing Edge voices
Wrap Flow, Liquidity and Volatility as BeeEvidence rather than rewriting them. Correct semantics remain explicit. Add Path Geometry and Cross-Market Bees. Add derivatives/carry only when public timestamp-correct history is available. Slower on-chain evidence stays in its own latency class.

### Phase S5: Queen Conducting Runtime
Implement QueenScorePage and QueenEpochReceipt. Wire the Triune Mind, waggle/notation calls, harmonic health and epoch transitions to Bee attention and Comparison requests. Preserve dissent and independent lineages. Quorum remains choreography, never majority agreement.

### Phase S6: Hypothesis Envelope
Bind world state, declared small variable set, comparisons, Bee evidence, Worker proposal, counterpoint, Triune interpretation, Queen notation/epoch and controls into one immutable envelope. No undeclared feature may influence settlement analysis.

### Phase S7: Causal Prosecution
Replay historical pages with deterministic organ masks. For every organ measure AVAILABLE -> INVOKED -> INFLUENTIAL -> HISTORICALLY_USEFUL. Run removal, shuffle, delayed-evidence, duplicate-lineage and false-unison attacks. Settle rejected candidates too.

### Phase S8: Learning and memory
Update Learning Ledger and crystals with regime-qualified knowledge: supported, contradicted, decayed, superseded, regime-dependent. Execution evidence cannot directly modify production authority. Pollen/reputation reward challenge, novelty, timing, falsification and settlement usefulness rather than agreement.

### Phase S9: Prospective Shadow Hive
Freeze surviving hypotheses, Queen epoch rules and evidence transforms. Observe genuinely unseen data. No retrospective threshold edits. Compare against primitive, random, no-trade and simpler nested controls. Apply realistic cost assumptions.

### Phase S10: Economic gate
Only after sufficient prospective evidence ask whether any mechanism remains positive after costs, dependence controls, selection regret and regime drift. This phase still does not imply live execution authority.

## Acceptance tests for the synthesis

The programme is not complete merely because every organ runs. It must prove:
- one canonical Market Memory and world_state_id;
- no future-data access;
- Bees have distinct evidence families and lineage;
- Workers remain proposal engines;
- Queen demonstrably changes research choreography/epoch;
- Triune roles are visible in receipts;
- harmonic state can change notation without becoming a verdict;
- quorum preserves dissent and rejects false unison;
- Comparison is simultaneous with hypothesis formation;
- selected and rejected candidates both settle;
- each organ has causal ablation evidence;
- historical and prospective authority remain separate;
- execution and promotion remain false throughout the research programme.
