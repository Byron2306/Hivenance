# Hivenance Phoenix Phase 7.1: Integration Reconciliation

This package preserves the heavy research integrations while enforcing one authority chain. External bots, ML, execution parity, the signal marketplace, the Config Agent, and the Event Spine remain research or diagnostic systems. Phase 6 alone may submit live orders. Phase 7 alone may scale capital stages.

See `PHASE7_1_OPERATOR_GUIDE.md` and run `python scripts/phase7_1_preflight.py`.

## System overview

Hivenance Phoenix is a **governed trading research and deployment pipeline**. Its job is not merely to emit signals. Its real job is to force every claim about edge through observation, research, execution simulation, validation, approval, and capital controls before any live order can exist.

At a high level, the stack behaves like this:

```text
public market observation
-> research hypotheses and baselines
-> execution simulation under costs and stress
-> adversarial validation
-> locked shadow flight
-> tiny live canary
-> controlled growth governor
```

That means the package is really four systems inside one:

- a public-market observation engine
- a hypothesis and model tournament
- a deterministic execution and microstructure simulation lab
- a governance and promotion chain that decides what is allowed to advance

The architecture is stronger on **evidence control, safety, and auditability** than on raw demonstrated profit. That is a strength, but it also explains why the system can feel conservative: it is designed to block weak claims rather than glamorize them.

## Phase breakdown

### Phase 1: Observation

Collects public-market data, filters symbols by liquidity and tradability, creates feature vectors, persists snapshots, and measures data quality. This is the sensor layer for everything downstream.

### Phase 2: Hypothesis lab

Runs frozen primary hypotheses, federated challengers, and baselines against the same observation stream. It asks whether any research model produces post-cost directional forecasts that are better than abstaining or than dumb baselines.

### Phase 3: Execution lab

Takes Phase-2 forecasts and simulates how they would behave under order policy, slippage, spread, latency, participation, and stress. This is where signal quality meets market reality.

### Phase 4: Adversarial validation

Runs a more serious court of appeal over simulated evidence, including robustness and overfitting pressure. This phase is supposed to reject attractive but fragile ideas.

### Phase 5: Shadow flight

Locks an approved model/policy configuration and creates paper-only intents. No live order routing is allowed here.

### Phase 6: Canary

Would allow tiny live deployment under hard guardrails, strict scope, and explicit approvals. In the current package state, this is still inactive.

### Phase 7: Growth governor

Would scale exposure only through a governed sequence of proposal, delay, approval, recheck, and activation. It is explicitly locked by default.

## Current operational snapshot

As of **Monday, August 3, 2026**, the system is best described as:

- **Phase 1 observation:** healthy and running.
- **Phase 2 hypotheses:** active and producing a large body of settled research evidence.
- **Phase 3 execution lab:** active, but most fresh runs are currently rejecting candidates with `FILTERED_NO_EDGE`.
- **Phase 4 validation:** still blocked from promotion.
- **Phase 5 shadow flight:** still locked and not generating intents.
- **Phase 6 live canary:** not active.

This means the stack is operational as a **research and governance system**, but it has **not yet earned a credible claim of deployable trading edge**.

## Piece-by-piece score

These scores are an honest read of the current system state on **Monday, August 3, 2026**.

- architecture clarity: **8.5/10**
- safety and governance: **9/10**
- observation quality: **8.5/10**
- feature and evidence plumbing: **8/10**
- hypothesis quality: **4.5/10**
- execution realism: **7.5/10**
- validation rigor: **7.5/10**
- frontend and operator usability: **6.5/10**
- profit readiness: **4/10**
- overall as a governed research platform: **8/10**
- overall as a live profit machine today: **4/10**

Interpretation:

- The system is unusually strong at structuring research, preserving evidence, and preventing unsafe promotion.
- The system is materially weaker at proving durable, post-cost alpha in the current live research record.
- In plain terms: this is a **good governed platform with a weak demonstrated edge**, not a bad system.

## What Is Actually Working

What is real today:

- Phase 1 is collecting market observations, ranking symbols, tagging tradability, and persisting durable snapshots.
- Phase 2 is generating frozen forecasts, settling them later, and building a real evidence ledger instead of hand-wavy backtests.
- Phase 3 is simulating execution under spread, slippage, latency, participation, and stress-policy assumptions.
- Phase 4 is rejecting premature promotion rather than letting attractive-but-fragile candidates slip through.
- The desktop stack can display compact backend snapshots without hanging on the large SQLite store.

What is not real yet:

- there is no earned right to scale capital
- there is no credible unattended live-profit claim
- there is no broad, repeatable, post-cost edge across the current candidate population

## Where The Bottleneck Is

The bottleneck is not observation quality anymore. It is the conversion from:

`observed market state -> forecast edge -> executable edge -> robust promoted edge`

The weakest link remains the middle of that chain:

- too many Phase-2 candidates are still negative after cost
- too few Phase-3 candidates survive live intake gates
- positive pockets exist, but they are still too selective and too small-sample to justify capital trust

That means the system should currently be treated as a **truth-seeking research and governance machine**, not as a proven profit engine.

## Startup

Desktop stack launcher:

```bash
./scripts/start_hivenance_desktop.sh
```

Direct desktop launcher:

```bash
env -u ELECTRON_RUN_AS_NODE PYTHON_BIN="$PWD/.venv-phase1/bin/python3" ./desktop-ui/start.sh
```

Research runners commonly used in this repo:

```bash
python scripts/run_phase1_observer.py --exchange kraken
python scripts/run_phase2_hypotheses.py
python scripts/run_phase3_execution_lab.py
```

# Hivenance Phoenix Phase 7: Controlled Growth Governor

This package contains the quarantined Hivenance pipeline through **Phase 7**.

- **Phase 1:** public-market observation and durable data-quality evidence.
- **Phase 2:** independent breakout and mean-reversion hypotheses with dumb baselines.
- **Phase 3:** deterministic execution simulation under venue, cost and infrastructure stress.
- **Phase 4:** adversarial validation with walk-forward, holdout, bootstrap, DSR and PBO-style diagnostics.
- **Phase 5:** human-approved, parameter-frozen public-market shadow flight.
- **Phase 6:** isolated, one-entry, USD 5 Kraken spot canary.
- **Phase 7:** evidence-gated, human-promoted growth stages with automatic demotion.

## Shipping state

Phase 7 ships **LOCKED**:

```text
phase7_stage_activation_enabled: false
phase6_live_submission_enabled: false
HIVENANCE_PHASE7_CONTROLLED_GROWTH: absent
HIVENANCE_PHASE6_LIVE_SUBMISSION: absent
active growth stage: CANARY / not activated
maximum packaged growth ceiling: USD 20
maximum simultaneous positions: 1
leverage: 1×
automatic promotion: false
```

## Growth doctrine

```text
Human proposal
→ cooling-off period
→ safety recheck
→ human approval
→ safety recheck
→ separate activation interlock
→ one controlled stage
→ fresh evidence block
```

Safety deterioration reverses direction immediately:

```text
UNKNOWN / incident / drawdown / rejection / slippage breach
→ automatic one-stage demotion
→ HALT
→ reconciliation
→ incident resolution
→ explicit human recovery at the lower stage
```

## Validate

```bash
for phase in 0 1 2 3 4 5 6 7; do
  python scripts/phase${phase}_preflight.py
done
python -m pytest -q
python scripts/phase7_synthetic_soak.py --json
```

## Safe inspection

```bash
python scripts/run_phase7_growth.py --status
```

The desktop **Growth Governor** is read-only. It contains no proposal, approval, activation, scaling, execution or recovery controls.

## Activation boundary

Do not create a Phase-7 proposal until the real Phase-6 database reports sufficient reconciled live evidence. Synthetic campaign artifacts validate engineering only and cannot unlock the governor.

## Phase 1-3 evidence summary

### Phase 1

- `observation_runs`: **1,554**
- `observation_snapshots`: **18,647**
- distinct observation days: **2**
- average recorded run quality: **1.0**
- latest observed runs on **August 2, 2026** were `HEALTHY`, repeatedly attempting **12** symbols, succeeding on **12**, and marking **11** eligible

Recent symbols show the observation layer is collecting usable public-market state rather than sitting idle. For example, the latest hour includes `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, and stablecoin pairs, with persisted spreads, depth, and quality metrics.

### Phase 2

- `hypothesis_forecasts`: **177,318**
- non-abstain forecasts: **39,575**
- settled non-abstain forecasts: **39,304**
- distinct hypothesis day count in the current store: **1**
- latest hypothesis runs on **August 1, 2026** were `HEALTHY`, each evaluating **12** symbols and producing **432** forecasts per run

Research scorecard highlights:

- `adapter_freqtrade_breakout_v1` is the only materially positive Phase-2 model in the current scorecard, but only on **20** settled non-abstain forecasts, which is not enough evidence to trust.
- The larger-sample research candidates are still negative after cost:
  - `candidate_freqai_transparent_linear_v1`: **1,623** settled trades, about **-25.96 bps** mean net
  - `candidate_finrl_conservative_policy_proxy_v1`: **1,257** settled trades, about **-25.78 bps** mean net
- Baselines are also negative, but “less bad than chaos” is not the same as profitable.

Practical conclusion: Phase 2 is absolutely working as a research engine, but it is **not yet proving robust positive edge**.

### Phase 3

- `simulation_runs`: **1,011**
- `simulated_orders`: **126,865**
- completed simulated orders: **89,723**
- simulation incidents recorded: **4,499**
- latest fresh runs on **August 2, 2026** are mostly `FILTERED_NO_EDGE`, with zero new simulations created in those cycles

Execution-lab highlights:

- There are genuinely positive simulation pockets for `candidate_freqai_transparent_linear_v1`, especially `passive_then_chase` and `passive_post_only` under `normal`, `cost_1_5x`, and some stress scenarios.
- Example strong pockets:
  - `candidate_freqai_transparent_linear_v1 :: passive_then_chase :: normal` at about **+21.07 bps**
  - `candidate_freqai_transparent_linear_v1 :: passive_then_chase :: cost_1_5x` at about **+20.71 bps**
  - `candidate_freqai_transparent_linear_v1 :: passive_post_only :: normal` at about **+20.37 bps**
- But the current live selection gate is still rejecting most recent candidate flow as having **no acceptable edge**.

Practical conclusion: Phase 3 shows that execution policy can sometimes rescue weak raw forecasts, but the current upstream signal stream is not consistently strong enough to feed it.

## Validation and shadow status

- Latest Phase-4 validation run: **August 1, 2026 09:31:50**
- Latest Phase-4 champion: `candidate_freqai_transparent_linear_v1::passive_then_chase`
- Latest Phase-4 `ready_for_phase5_review`: **false**
- Latest recorded PBO estimate: **0.07142857**
- Latest Phase-5 shadow run: **August 1, 2026 08:12:37**
- Latest Phase-5 status: `LOCKED_AWAITING_HUMAN_APPROVAL`
- Phase-5 intents created: **0**

So the governance chain is doing its job: nothing unsafe or unearned has been promoted downstream.

## Recent system additions

Recent work in this branch materially improved the research stack even though it has not yet produced a deployable profit claim:

- Added a desktop launcher that correctly prefers `.venv-phase1`:
  - `./scripts/start_hivenance_desktop.sh`
- Patched `desktop-ui/start.sh` to detect `.venv-phase1` automatically.
- Improved Phase-2 research federation so previously silent challenger models can emit some non-abstain forecasts:
  - configurable federation score scaling
  - configurable FreqAI confidence floor
  - move proxy logic combining ATR-style and signal-implied move estimates
- Hardened Phase-3 candidate intake gates:
  - expected net threshold
  - probability threshold
  - historical realized net threshold
  - historical sample threshold
  - research-candidate preference
  - cap on simulations per forecast
- Extended Phase-5 shadow intake to reject already expired forecasts and respect current time when selecting candidates.
- Improved Phase-4 validation sampling to use a more balanced per-candidate/per-scenario dataset slice.
- Upgraded the desktop validation page to surface champion, pass/fail summary, robustness, and top failure context.

## Honest Evaluation

This is **not yet a system I would trust to trade unattended for profit**.

The strongest parts:

- governance and authority boundaries are better than most hobby or even semi-serious trading stacks
- observation capture is live, durable, and useful
- execution simulation is materially more realistic than a simple backtest-only workflow
- the platform now has enough structure to falsify bad ideas instead of merely generating them

The weakest parts:

- the main research population still does not show broad positive post-cost performance
- the execution lab is finding some positive pockets, but not enough robust throughput
- sample quality is still uneven, with too much dependence on narrow slices and conditional wins
- profitability is still more of a thesis than a demonstrated fact

My honest judgment:

- as a governed research platform: **strong**
- as a capital-preserving decision framework: **promising**
- as a current profit machine: **not there yet**

If I were making the call purely on evidence, I would say:

1. Keep running Phase 1 and Phase 2 to deepen settled evidence.
2. Keep improving candidate selection and regime-specific routing.
3. Do not treat synthetic passes or isolated positive simulation pockets as proof of edge.
4. Do not unlock meaningful live capital until a candidate family stays positive after cost, after execution modeling, and after adversarial review with enough samples to matter.

That may sound conservative, but it is the correct kind of conservative. The system is doing something valuable already: it is preventing us from lying to ourselves about profit.

See:

- `PHASE7_OPERATOR_GUIDE.md`
- `PHASE7_CHANGELOG.md`
- `PHASE7_VALIDATION_REPORT.md`
- `PHASE7_SYNTHETIC_GROWTH_REPORT.json`
