# HiveNance Full Integration Wiring Audit — 2026-09-19

Branch: `hivenance-phoenix-edge-ecology`  
Audited head: `ce77cc7abdda4871123d6b9f206bd74aa9e3c097`  
Authority: research only. Execution and promotion remain false.

## Executive verdict

The integration programme is **not fully wired**.

A large amount of the planned organism exists in code, and several pieces are active in one runtime or another, but the current live G0/G1 path is still a **reduced synthesis slice**. The strongest defect is not absence of intelligence. It is that intelligence remains fragmented across parallel paths.

The current system has at least five materially distinct cognition paths:

1. canonical MarketMemory / WorldState replay;
2. Phoenix ObservationSwarm / HypothesisSwarm / HypothesisCompetition;
3. G0/G1 WorldGraph / SynthesisRuntime / organ ablation;
4. legacy RegimeOracle / Council / GovernanceQueen / SwarmGuard;
5. full Polyphonic / VNS / motif / resonance / Mystique / metabolism / ConductingQueen fabric.

They are not yet one fully composed runtime organism.

This means the current positive G1 veto evidence is real for the tested slice, but it must **not** be described as a test of the complete HiveNance architecture.

---

# 1. Long-horizon temporal truth

## 1.1 MarketMemory and replay world state exist

`agents/market_memory.py` is an append-only research memory.

`scripts/backfill_market_memory.py` backfills public Kraken OHLCV for:

- 1m
- 5m
- 15m
- 1h
- 4h
- 1d
- 1w

`agents/world_state.py::WorldStateBuilder` derives:

- 15m
- 1h
- 4h
- 24h
- 7d
- 30d
- 365d

Therefore the remembered week/month/year design is real.

### Critical gap

The current G0 live path does **not** build from `WorldStateBuilder`.

Instead, `g0_live_loop.py` constructs a new `CanonicalScoreFrame` directly from the current Phase-1 `FeatureVector`.

The 365d replay context is therefore currently **DISCONNECTED from G0/G1**.

---

## 1.2 A live CEX multi-horizon oracle also exists

`DataStoreAgent.cex_market_oracle_context()` derives:

- 1h
- 5h
- 24h
- 7d
- 30d

from timestamp-bounded Phase-1 observation snapshots.

`CexMultiHorizonMarketOracle` consumes those horizons with explicit weights:

- 1h: 0.34
- 5h: 0.26
- 24h: 0.20
- 7d: 0.12
- 30d: 0.08

and produces a research-only UP/DOWN/ABSTAIN forecast.

This is an actual directional model, not merely descriptive context.

### Critical gap

The current G1 veto-probe target roster is:

- `baseline_simple_momentum_v1`
- `baseline_simple_mean_reversion_v1`
- `baseline_deterministic_random_v1`

The CEX multi-horizon oracle is therefore **not part of the current G1 campaign**.

The recent 300-second G1 result says nothing about whether the multi-horizon oracle improves the final Hive conclusion.

---

## 1.3 Current G0 Horizon adapter truncates long context

`g0_live_evidence.py::horizon_from_feature()` currently consumes approximately:

- 2m
- 5m
- 15m
- 1h
- 24h

It does **not** consume the already-available CEX oracle:

- 5h
- 7d
- 30d

and it does not consume WorldStateBuilder's:

- 4h
- 7d
- 30d
- 365d

This is a genuine missed integration.

---

# 2. Phase S0-S10 status audit

## S0 — Preserve and census

**Status: SUBSTANTIALLY COMPLETE**

The repository contains strong census documents and overlap prosecutions. Major distinctions were explicitly captured:

- TemporalTexture != Temporal Participation;
- PolyphonicQuorum != Council consensus;
- ConductingQueen != legacy GovernanceQueen;
- synthetic Mystique != observed Comparison;
- Evidence Bees != Workers;
- transformation != lineage != independent evidence root.

The census itself correctly identified runtime composition as the main gap.

---

## S1 — Common Evidence Contract

**Status: PARTIAL**

`WorldGraphNode` provides:

- world_state_id/hash;
- family;
- evidence roots;
- lineage id;
- transformation id;
- freshness;
- uncertainty;
- synthetic namespace;
- authority ceiling.

That is a strong substrate.

However the originally specified common BeeEvidence contract was richer and explicitly required:

- source_kind;
- source ids;
- observed_at;
- available_at/source timestamps;
- missingness/abstention;
- transformation version.

These are not uniformly first-class on every graph node.

There is no single canonical `BeeEvidence` adapter used by every Evidence Bee.

### Verdict

The graph contract replaced part of S1, but S1 did not fully close.

---

## S2 — Temporal Participation Bee

**Status: IMPLEMENTED AND G0-WIRED**

`TemporalParticipationBee` correctly includes:

- UTC hour;
- weekday/weekend;
- 4h UTC block;
- broad session clock proxies;
- same-hour historical volume normalization;
- optional realized-move normalization;
- evidence root;
- research-only authority.

Current G0 live construction supplies historical volume but generally leaves `realized_move_bps=None`, so the move-normalization half is not active.

The organ has now produced prospective G1 veto evidence.

---

## S3 — Comparison Engine

**Status: ENGINE IMPLEMENTED, LIVE WIRING PARTIAL**

The engine implements:

- same UTC hour baseline;
- cross-section;
- selected vs rejected;
- event vs control;
- nearest prior states.

The current G0 adapter invokes only:

- `same_utc_hour_baseline`.

Therefore current live Comparison is **not** the full S3 design.

Missing from the live G0 cycle:

- cross-sectional comparison;
- selected vs rejected selection-regret comparison;
- nearest prior world-state matching;
- event vs matched control;
- conflict/non-conflict matched controls;
- explicit random/no-trade/time-shift comparison nodes.

---

## S4 — Edge voices and additional Bees

**Status: PARTIAL / MISLEADINGLY NARROW IN G0**

The repository contains broader Edge Ecology machinery.

However current `g0_live_loop.py` constructs its Edge snapshot with only:

- `LIQUIDITY`

using bid depth, ask depth and spread.

It does not currently place actual Flow testimony into that G0 Edge snapshot.

Therefore the current G1 organ label `edge_ecology` is testing a much narrower live intervention than the name implies.

Not fully live-composed in G0:

- Flow Evidence;
- Volatility Evidence;
- Path Geometry;
- Cross-Market Bee;
- timestamp-correct Derivatives/Carry Bee;
- Information Arrival;
- slow Capital/On-chain evidence.

Some related information exists elsewhere in Phoenix, but it is not one WorldGraph evidence composition.

---

## S5 — Queen Conducting Runtime

**Status: IMPLEMENTED ENGINE, REDUCED LIVE BRIDGE**

`ConductingQueen.conduct()` can hear:

- VNS pulses;
- VNS phrase;
- harmonic context;
- TemporalTexture;
- EdgeChorus;
- motif hunting;
- colony correlations;
- causal cascade;
- HivePulse;
- PolyphonicResonance;
- Mystique falsification;
- CognitiveMetabolism;
- learned challengers;
- motif;
- entrainment;
- governance epoch;
- canonical world frame.

The current `g1_conducting_queen_bridge.py` supplies only:

- graph-derived notes;
- motif accumulator;
- polyphonic entrainment;
- a fresh governance epoch;
- canonical frame.

The following Queen channels therefore fall back to default/unheard values in the current G1 path:

- VNS pulses/phrase;
- TemporalTexture;
- EdgeChorus;
- hunt matches;
- correlations;
- cascade;
- HivePulse;
- PolyphonicResonance;
- Mystique;
- CognitiveMetabolism;
- learned challengers;
- explicit harmonic context.

This explains why the current G1 `conducting_queen` is **not a test of the full ConductingQueen**.

### Additional gap: no reciprocal conducting loop

The design called for:

Queen -> notation/epoch -> new Bee/Comparison/challenge requests -> updated WorldGraph -> Queen again.

Current `SynthesisRuntime` emits `attention_obligations` and `organ_requests`, but the G0 live cycle does not execute those requests and recur.

The Queen is currently a mostly one-pass post-cognition gate, not the reciprocal conductor described in the architecture.

---

## S6 — Immutable Hypothesis Envelope

**Status: PARTIAL / NOT CANONICAL**

G0 twins preserve:

- world hash;
- full/ablated cognition hashes;
- full/ablated intents;
- campaign/target lineage.

`bind_synthesis_context()` also attaches a QueenView-derived context to a FeatureVector.

But there is no single immutable canonical envelope that binds, for one hypothesis:

- WorldState / CanonicalScoreFrame;
- all declared Bee evidence;
- all comparisons;
- Worker proposal;
- counterpoint;
- Triune interpretation;
- Queen notation/epoch;
- controls;
- declared variable set.

S6 is therefore not complete.

---

## S7 — Causal Prosecution

**Status: STRONG PARTIAL IMPLEMENTATION**

G0/G1 now provides real prospective paired ablation for:

- edge_ecology;
- horizon_context;
- temporal_participation_bee;
- learning_memory;
- comparison_engine;
- polyphonic_quorum;
- conducting_queen.

This is valuable and is producing meaningful evidence.

However the planned causal prosecution covered the whole organism and attacks including:

- removal;
- shuffle;
- delayed evidence;
- duplicate-lineage;
- false-unison;
- selection regret;
- same-root dependence.

Current G1 does not prosecute:

- RegimeOracle;
- CEX multi-horizon oracle;
- 365d WorldState context;
- workers;
- crystal memory;
- medium-horizon trend model;
- derivatives trend model;
- VNS stream;
- TemporalTexture;
- EdgeChorus;
- motif hunting;
- colony correlation;
- cascade;
- HivePulse;
- resonance;
- harmonic governance;
- Mystique;
- metabolism;
- learned ML challenger;
- Pollen/reputation.

S7 is therefore not the full prosecution programme yet.

---

## S8 — Learning and memory

**Status: PARTIAL / ONE KNOWN SAFETY GAP**

Implemented:

- LearningMemory;
- retrieval;
- attention obligations;
- crystal memory;
- positive/negative capability context;
- Shadow Court learning;
- learning authority separation.

Known unresolved issue:

`latest_shadow_learning(data_store)` currently retrieves learning too broadly because the canonical Shadow Court learning receipt does not yet carry/filter the complete:

- model_id;
- symbol;
- horizon_seconds;
- forecast_id;
- direction

context needed for exact applicability.

Until repaired, `learning_memory` must not be trusted as a live causal veto.

Also missing from the composed runtime:

- regime-qualified decay/supersession recurrence;
- Queen-triggered learning requests actually being executed;
- Pollen/reputation updates feeding the same prospective organism.

---

## S9 — Prospective Shadow Hive

**Status: PARTIAL AND ACTIVE**

The current G1 programme correctly freezes prospective interventions before outcomes and keeps:

- execution false;
- promotion false;
- public data only;
- no private endpoints;
- no real orders.

The current campaign has already produced one valid narrow result:

`temporal_participation_bee` is a prospective utility candidate on the 300-second baseline-proposal veto substrate.

But S9 was specified as the **full surviving Hive**, not a three-baseline veto probe.

The current campaign excludes many major directional and contextual systems.

---

## S10 — Economic gate

**Status: NOT REACHED FOR THE FULL HIVE**

Current G1 utility is a component-level economic gate.

The full S10 question remains unanswered:

Does the complete multi-horizon, comparison-rich, independent-evidence, Queen-conducted Hive produce better prospective post-cost conclusions than simpler nested controls?

---

# 3. Phoenix directional cognition that exists but is not in the current G1 target

## 3.1 CEX Multi-Horizon Market Oracle

Active Phase-2 research candidate:

`candidate_cex_multi_horizon_oracle_v1`

It uses:

- 1h;
- 5h;
- 24h;
- 7d;
- 30d;

and explicitly emits UP/DOWN/ABSTAIN.

This should be treated as a first-class directional voice in the eventual Full Hive Directional Synthesis experiment.

---

## 3.2 Medium Horizon Trend

`MediumHorizonTrendModel` is a real Phase-2 research path.

Default forecast horizon is around 24h, with accepted historical slices and prospective forecasts.

It is invoked separately by HypothesisSwarm when accepted medium-horizon receipts exist.

It is not in the current G1 target.

---

## 3.3 Derivatives Trend

`DerivativesTrendModel` is also invoked separately when accepted derivatives receipts exist.

Configured research horizons include approximately:

- 12h;
- 24h;
- 3d.

It includes a worker-coalition veto layer.

It is not in the current G1 target.

---

## 3.4 Advanced Systems / Triune Polyphonic candidate

`candidate_triune_polyphonic_synthesis_v1` exists in the Phase-2 federation.

Important qualification:

It is **not the actual live full Polyphonic/Queen organism**.

`AdvancedSystemsMarketSynthesizer` is a deterministic local proxy over a FeatureVector with source-file fingerprints. It locally reproduces concepts named VNS, CCE, Triune, polyphonic resonance, Seraph, Sophia and Mandos.

Therefore it must not be mistaken for proof that the actual VNS -> Motif -> Entrainment -> Hunting -> Correlation -> Cascade -> HivePulse -> Resonance -> Mystique -> Metabolism -> ConductingQueen chain is runtime-composed.

---

# 4. Canonical memory split still exists

The architecture required:

**one organism, one memory spine**.

Current reality still includes at least:

1. `data/hivenance_market_memory.db` via MarketMemory;
2. Phoenix/DataStore `observation_snapshots`;
3. Horizon's historical/local context lineage;
4. crystal registry;
5. phase-specific evidence tables.

The most important current live oracle, `cex_market_oracle_context()`, reads Phoenix `observation_snapshots`, not MarketMemory.

The WorldStateBuilder reads MarketMemory, but G0 does not use the WorldStateBuilder.

Therefore the canonical-memory acceptance condition is **not yet met**.

---

# 5. RegimeOracle remains outside the G0 causal organism

`agents/oracle_regime.py` is a real multi-timeframe regime classifier and is active in the legacy Coordinator path.

It is not invoked by `SynthesisRuntime` or isolated as a G0/G1 organ.

A `regime_inputs` feature is present elsewhere in Phoenix, but that is not equivalent to proving the legacy RegimeOracle's marginal contribution.

The planned RegimeOracle ablation remains outstanding.

---

# 6. CoinSelector and rejected-universe settlement are incomplete in G0

The synthesis acceptance tests required:

- selected candidates settle;
- rejected candidates also settle;
- selection regret is measurable.

Current G0 processes Observation candidates that reached the candidate loop.

The live Comparison adapter does not invoke `selected_vs_rejected()`.

Therefore current G1 cannot answer whether CoinSelector is discarding better opportunities than it keeps.

This is a material missing experiment.

---

# 7. Current Polyphonic Quorum is a reduced bridge

The canonical quorum semantics are correct:

- world-bound;
- independent-root aware;
- role/family diverse;
- dissent-preserving;
- not a majority vote.

However `g1_polyphonic_bridge.py` builds its notes only from:

- the Phoenix forecast CALL;
- nodes currently present in the reduced SynthesisRuntime QueenView.

Because the underlying G0 WorldGraph contains only a subset of the planned evidence fabric, current quorum is not hearing the complete orchestra.

No current G1 divergence from quorum must be interpreted in that context.

---

# 8. Pollen / reputation are not in the current G1 organism

Pollen and reputation have dedicated prospective machinery elsewhere.

They are not part of the current G0 live experiment set.

Therefore the current G1 says nothing about whether:

- Queen-issued research incentives;
- reputation;
- challenge priority;
- settlement reward

improve the complete organism.

---

# 9. What the current positive G1 result DOES prove

The current campaign remains valuable.

It prospectively demonstrates that, on the current 300-second baseline-proposal substrate, Temporal Participation produced a statistically qualified veto utility signal under the frozen G1 policy.

It also shows immature positive signals for Comparison, Horizon and Edge/Liquidity.

Those findings are not invalidated by this audit.

They are simply narrower than the full HiveNance claim.

Correct interpretation:

> The reduced live synthesis slice has demonstrated useful abstention/cost-avoidance behavior.

Incorrect interpretation:

> The complete multi-horizon HiveNance organism has now been tested.

It has not.

---

# 10. Repair programme

No threshold tuning should occur while repairing composition.

## R0 — Freeze current evidence

Preserve:

- current G1 campaign;
- all frozen twins;
- settlement receipts;
- existing G1 policy;
- current positive/negative findings.

Do not rewrite them after architecture repair.

## R1 — Canonical memory bridge

Make every live synthesis cycle able to read a timestamp-bounded `WorldStatePage` derived from MarketMemory while preserving the CanonicalScoreFrame as observed root.

Import live Phase-1 observations into MarketMemory or provide a deterministic bound adapter.

Exit:

- same world_state_id lineage is traceable from current observation through long-memory interpretation;
- no second truth universe.

## R2 — Full Horizon lattice

Expose separately, without false independence:

- micro: 10s/30s/2m/5m;
- meso: 15m/1h/4h/24h;
- macro: 7d/30d/365d;
- active CEX oracle: 1h/5h/24h/7d/30d.

Do not flatten these into one vote.

Bind roots so price transforms are not counted as independent witnesses.

## R3 — Complete Comparison composition

In one live world cycle create:

- same-hour baseline;
- cross-section;
- selected vs rejected;
- nearest prior states;
- conflict vs non-conflict where labels exist;
- event vs control where provenance exists;
- random/no-trade/time-shift controls.

## R4 — Complete evidence-family adapters

Wire:

- actual public trade Flow;
- Liquidity;
- Volatility;
- Cross-Market;
- Path Geometry.

Only add derivatives/carry when the timestamp-correct public source is genuinely present.

## R5 — Regime / worker / crystal integration

Add explicit WorldGraph nodes and causal masks for:

- RegimeOracle;
- Worker proposals;
- positive crystal memory;
- negative crystal memory;
- medium-horizon trend context;
- derivatives trend context;
- CEX multi-horizon oracle.

Preserve proposal vs evidence distinctions.

## R6 — Full Polyphia Queen input assembly

Build all already-implemented Queen inputs from the same frozen frame:

- VNS pulses;
- VNS phrase;
- TemporalTexture;
- EdgeChorus;
- motif hunting;
- colony correlation;
- CausalCascade;
- HivePulse;
- PolyphonicResonance;
- harmonic context;
- Mystique;
- CognitiveMetabolism;
- learned challenger receipts.

No default `UNHEARD` value should silently pass as integration.

Every Queen receipt should explicitly list PRESENT / ABSENT / NOT_APPLICABLE for each channel.

## R7 — Reciprocal conducting loop

Execute Queen research notation as bounded research requests:

Queen -> request -> Bee/Comparison/challenge -> graph update -> Queen.

Set a deterministic maximum recurrence count and preserve the same immutable observed root.

## R8 — Canonical hypothesis envelope

Freeze one complete envelope per directional conclusion containing:

- observed root;
- long-horizon lattice;
- evidence nodes;
- comparisons;
- candidate/worker proposals;
- dissent;
- quorum;
- Triune scores;
- Queen receipt/epoch;
- controls;
- predicted direction;
- predicted move;
- cost;
- net;
- all evidence roots.

## R9 — Full-organism causal gauntlet

Prospectively compare:

- FULL_HIVE;
- Phoenix-only;
- CEX oracle-only;
- simple momentum;
- simple reversion;
- deterministic random;
- no-trade;
- single-horizon controls;
- organ ablations.

Also prosecute:

- delay;
- shuffle;
- duplicate-lineage;
- false-unison;
- stale world;
- missing voice.

## R10 — Learning binding repair

Before LearningMemory is allowed to influence live research, bind Court learning to:

- model_id;
- symbol;
- horizon_seconds;
- forecast_id;
- direction;
- world/regime applicability.

Positive learning may not boost authority. Negative evidence may only influence within its proven scope.

## R11 — Prospective Full Hive Directional Synthesis

Freeze the repaired organism before outcomes.

For each horizon report:

- UP / DOWN / ABSTAIN;
- confidence;
- expected move;
- predicted costs;
- expected net;
- supporting roots;
- dissenting roots;
- independent-root count;
- Queen/Triune reasoning receipt.

Settle every conclusion against unseen public tape.

---

# 11. Priority findings

## P0 — must fix before claiming full Hive evidence

1. MarketMemory / WorldState not in G0 live composition.
2. 7d/30d/365d long-horizon lattice not fully fed to G0 synthesis.
3. CEX multi-horizon directional oracle excluded from current G1 target.
4. Queen bridge supplies only a small subset of her implemented senses.
5. reciprocal Queen research loop is absent.
6. Comparison live adapter uses only same-hour comparison.
7. Edge G0 currently represents primarily Liquidity, not full Edge Ecology.
8. RegimeOracle is not G0/G1-prosecuted.
9. selected/rejected selection-regret settlement is not live-composed.
10. LearningMemory applicability binding remains unsafe/incomplete.

## P1 — next integration tier

11. VNS phrase/TemporalTexture/EdgeChorus/hunting/correlation/cascade/HivePulse/resonance.
12. Mystique and CognitiveMetabolism.
13. worker/crystal/medium-trend/derivatives context as explicit graph nodes.
14. Pollen/reputation causal tests.
15. explicit common BeeEvidence adapter completion.

---

# 12. Final audit conclusion

The architecture was not lost.

Most of the ambitious pieces are actually present.

The problem is that implementation proceeded in **parallel slices**, and the recent G0/G1 programme composed only the smallest safe subset needed for causal experimentation.

That was scientifically useful, but it also means several integration promises from the S0-S10 plan remain unfulfilled.

The correct next objective is therefore:

**HIVENANCE FULL ORGANISM RECOMPOSITION**

not another strategy and not threshold tuning.

Success means one timestamp-bound public market world is heard simultaneously by the long-memory Horizon/Oracle system, Comparison, Edge evidence, workers/crystals, VNS/Polyphia, Quorum and the full ConductingQueen, with Phoenix freezing and settling the resulting directional hypothesis without granting execution authority.
