# HiveNance Phase 12.7c9 — Learning → Crystal → Hypothesis Feedback Repair

Status: **IMPLEMENTED, AWAITING LOCAL ACCEPTANCE TESTS**

## Objective

Repair the Phoenix feedback loop so settled research evidence can materially and deterministically influence later hypothesis research without acquiring execution authority.

The intended loop is:

```
settled forecast outcomes
        ↓
point-in-time reuse statistics
        ↓
Learning applicability
        ↓
bounded research prior
        ↓
HypothesisCompetition
        ↓
forecast / abstention
        ↓
learning Crystal materialization
        ↓
next-cycle exact applicability lookup
        ↺
```

## Authority boundary

Learning and Crystal reuse may:

- strengthen confidence in an already supported research forecast;
- reduce uncertainty;
- provide bounded adaptive-threshold support for a borderline hypothesis;
- veto an otherwise active forecast when sufficiently strong negative prior evidence applies;
- change research-route priority and provenance.

Learning and Crystal reuse may **not**:

- invent current market evidence;
- flip a forecast direction;
- manufacture an expected market move;
- grant execution eligibility;
- grant promotion eligibility;
- bypass point-in-time settlement or applicability checks.

All emitted learning priors use authority `RESEARCH_PRIOR_ONLY`.

## BEAST-derived reuse pattern

The repair adapts the BEAST Phase-7 pattern rather than copying BEAST's execution semantics.

Lifecycle:

```
NO_PRIOR_EVIDENCE
      ↓
ADVISORY
      ↓
SCAFFOLDED
      ↓
DETERMINISTIC_RESEARCH_REUSE_CANDIDATE
      ↓
DETERMINISTIC_CRYSTAL_REUSE
```

A stored Crystal does not become reusable merely because it exists. The current cycle must independently reproduce the same applicability key and still satisfy current evidence gates.

If current evidence no longer passes, the same deterministic Crystal ID is updated to a weaker lifecycle and cannot reactivate itself.

## Point-in-time safety

`ResearchReuseGovernor.decide(..., as_of_ts=...)` now forwards an historical cutoff into both exact and transformed reuse statistics.

The datastore queries enforce:

```
outcome.settled_ts <= as_of_ts
```

Historical replay therefore cannot consume future settlements.

## Applicability boundary

The learning applicability key binds at least:

- symbol;
- symbol class;
- cohort bucket;
- regime;
- liquidity state;
- participation state;
- feature version;
- model ID;
- horizon;
- research configuration hash.

A Crystal from a materially different applicability boundary is not reused.

## Positive learning

Positive evidence does not create a trade from nothing.

It can:

- lower bounded adaptive-recovery thresholds;
- raise probability-positive-net by a capped amount;
- reduce uncertainty by a capped amount;
- slightly strengthen raw research score.

An already abstaining forecast remains abstaining unless the pre-forecast adaptive-threshold path lawfully activates the model from current market evidence plus the bounded reusable prior.

## Negative learning

Strong negative evidence can veto an active research forecast.

The veto:

- returns `ABSTAIN`;
- clears expected move/net fields;
- records `learning_prior_negative_reuse_veto`;
- remains `execution_eligible=False`.

## Crystal persistence and deterministic reuse

Qualifying priors are materialized in the existing Crystal registry with:

- `crystal_family=learning_reuse`;
- `artifact_class=market_learning_crystal`;
- deterministic `crystal_id` derived from applicability;
- lifecycle and evidence metrics;
- expiry;
- `research_prior_only` authority.

On a later cycle, the swarm retrieves `learning_reuse` Crystals for the current symbol/regime before hypothesis competition.

Reuse is recorded only when:

1. the Crystal applicability key exactly matches the newly compiled applicability key;
2. the Crystal has not expired;
3. its stored lifecycle is `DETERMINISTIC_RESEARCH_REUSE_CANDIDATE`;
4. current point-in-time evidence independently still qualifies for the same lifecycle.

The resulting mode is `DETERMINISTIC_CRYSTAL_REUSE`.

## Modified files

- `agents/data_store_agent.py`
- `strategies/volatility_breakout/research_reuse.py`
- `strategies/volatility_breakout/learning_crystal_feedback.py`
- `strategies/volatility_breakout/hypothesis_competition.py`
- `strategies/volatility_breakout/hypothesis_swarm.py`
- `tests/test_learning_crystal_feedback_phase12.py`

## Acceptance tests

The repair is not Phase-12 accepted until local tests prove:

1. positive settled reuse compiles before prediction;
2. future-settled evidence is refused;
3. stale evidence is challenged/demoted;
4. positive reuse changes bounded research confidence without changing direction or expected move;
5. negative reuse can veto;
6. positive prior alone cannot resurrect an abstaining forecast;
7. Crystal materialization is deterministic;
8. exact applicability allows next-cycle Crystal reuse;
9. applicability mismatch refuses Crystal reuse;
10. positive reusable prior can activate bounded adaptive recovery on a controlled borderline fixture;
11. existing historical/reuse/hypothesis regressions remain green.

## Phase-12 disposition

Previous `NO_LEARNING` and `NO_CRYSTALS` historical dispositions are now **provisional**.

They must be rerun after this repair is accepted because the earlier historical path did not exercise the intended Learning → Crystal → Hypothesis feedback loop.

No profitability, prospective edge, execution, or promotion claim is made by this repair.
