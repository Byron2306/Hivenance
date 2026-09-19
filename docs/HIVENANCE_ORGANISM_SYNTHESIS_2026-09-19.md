# HiveNance Organism Synthesis Decision

Date: 2026-09-19
Status: IMPLEMENTATION DECISION
Authority: research only; no execution or promotion authority

## Decision

HiveNance will have **one organism, one memory spine, multiple independently
testable organs**. We will not choose one of the five historical architectures
and discard the others. Their strongest responsibilities are complementary.

The canonical control plane is Phoenix because it already encodes the scientific
boundary: public observation -> hypothesis -> prospective forecast -> settlement
-> validation, without execution authority.

## The five architectures become layers

1. **Coordinator / legacy swarm -> Worker and safety adapter layer.**
   Keep StrategyWorkers, Council, RegimeOracle, GovernanceQueen, SwarmGuard and
   operational adapters. Stop treating the Coordinator's private cache as the
   organism's memory.

2. **Phoenix -> canonical research lifecycle.**
   Own experiment identity, hypotheses, prospective forecasts, counterfactuals,
   settlement, validation and promotion evidence.

3. **Polyphonic / Pollen -> deliberation semantics.**
   Keep independent evidence lineage, counterpoint, quorum choreography, Queen
   resolution, Pollen and reputation. These are candidate decision organs, not
   assumed alpha. Their marginal contribution must be ablated.

4. **Horizon observer -> temporal and cross-sectional perception.**
   Own micro/meso/macro context, relative strength, breadth and temporal
   alignment. Its private SQLite history becomes an input/importer to the
   canonical Market Memory rather than a separate truth universe.

5. **Edge Ecology -> economic state voices.**
   Flow, liquidity, trend, volatility, carry and ML challenge become independent
   world-state features available to Phoenix experiments. Edge Ecology must not
   bypass the Phoenix evidence lifecycle.

## One memory line

Every meaningful fact is written as an immutable timestamped Market Memory line:

    source + kind + symbol + effective time + observed time
    + world-state binding + payload + content hash
    + research-only authority

Raw OHLCV bars are also indexed in a normalized table, but every bar receives a
corresponding memory line. The spine is append-only and deterministic/idempotent.

Initial implementation:
- agents/market_memory.py
- scripts/backfill_market_memory.py
- data/hivenance_market_memory.db (runtime artifact)

Historical reconstruction and prospective proof are explicitly different.
Backfilled data may be used to generate, mutate and reject hypotheses. It may not
be presented as prospective proof. Promotion evidence must come from forecasts
frozen before their outcome.

## Canonical flow

    PUBLIC MARKET / HISTORICAL BACKFILL
                 |
                 v
          MARKET MEMORY SPINE
                 |
       +---------+----------+
       |         |          |
       v         v          v
    Horizon   Regime     CoinSelector
       |         |          |
       +---------+----------+
                 v
          WORLD STATE PAGE
                 |
       +---------+----------+
       |                    |
       v                    v
    Edge voices      legacy workers/crystals
       |                    |
       +---------+----------+
                 v
       Polyphonic counterpoint/quorum
                 |
                 v
         Phoenix hypothesis lifecycle
                 |
        prospective forecast
                 |
                 v
             settlement
                 |
                 v
       causal ablation receipts

SwarmGuard remains a safety/policy gate. It must not be confused with market
prediction.

## Historical mutation laboratory

Historical memory is allowed to answer:
- Would CoinSelector have ranked the eventual opportunity?
- Does Horizon context improve a frozen rule relative to the same rule without it?
- Does RegimeOracle alter admission beneficially?
- Do crystals improve decisions or merely repeat correlated evidence?
- Do Flow/Liquidity/ML vetoes add value?
- Do quorum, counterpoint, Queen, Pollen or reputation improve outcomes?
- Which combinations are redundant?

Every mutation is evaluated on the same timestamped world states with paired
counterfactuals. Search results are discovery evidence only.

A mutation that looks promising must be frozen and tested prospectively before it
can count as durable evidence.

## Causal organ states

Every organ in a decision receipt receives one of:

- AVAILABLE: implementation/data exists.
- INVOKED: called for this world state.
- INFLUENTIAL: changing/removing it changes the decision.
- USEFUL: paired outcome is better after costs on the evaluation set.
- PROSPECTIVE_USEFUL: usefulness survives a frozen prospective run.

No organ is called useful merely because it ran.

## Immediate implementation sequence

S1. Canonical Market Memory and public multi-timeframe backfill.
S2. Import existing Horizon history and Phoenix/Edge evidence into memory without
    rewriting provenance.
S3. World State Page builder that binds CoinSelector, Horizon, RegimeOracle,
    crystals/workers and Edge voices to the same timestamp.
S4. Historical replay harness with deterministic organ masks.
S5. Causal receipts and paired ablation report.
S6. Freeze the best *mechanistic* candidate(s), then run prospective validation.

## Non-negotiable boundaries

- no private exchange endpoints in the research memory/backfill path;
- no historical result may be relabeled as prospective;
- no optimizer may tune on its evaluation slice;
- random and no-trade controls remain first-class;
- transaction costs are applied before economic claims;
- rejected coins are settled too, enabling selection-regret measurement;
- execution and promotion remain false until separate gates explicitly prove them.
