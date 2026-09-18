# Hivenance Phoenix Phase 7.1: Integration Reconciliation

This package preserves the heavy research integrations while enforcing one authority chain. External bots, ML, execution parity, the signal marketplace, the Config Agent, and the Event Spine remain research or diagnostic systems. Phase 6 alone may submit live orders. Phase 7 alone may scale capital stages.

See `PHASE7_1_OPERATOR_GUIDE.md` and run `python scripts/phase7_1_preflight.py`.

## Governed advanced-system synthesis

Phase 2 now includes `candidate_triune_polyphonic_synthesis_v1`, a cold-start
research challenger built from bounded patterns in the owner's VNS, CCE,
Triune, polyphonic resonance, Seraph, Sophia, and Mandos implementations. Every
forecast carries source-file digests, independent sensor quality, preserved
dissent, adaptive adversarial challenges, and a hash-chained decision receipt.
It has research-proposal authority only and cannot promote a model or submit an
order.

Run a fast outcome-blind audit against the latest observation snapshot:

```bash
./.venv-phase1/bin/python scripts/audit_advanced_synthesis.py --json
```

The first real audit on August 5, 2026 produced 0 proposals from 36 forecasts.
The leading BTC/USD and ETH/USD setups were coherent but predicted only about
9.5 bps of movement against roughly 25 bps of configured round-trip research
cost. This is useful refusal evidence, not demonstrated profit. The challenger
must still accumulate settlements and pass walk-forward calibration, execution
simulation, adversarial validation, and human-controlled promotion.

## Rapid profit lab

The current wallet is empty and the executor agent is disabled, so the correct
near-term profitability path is **public-data paper evidence**, not Phase-6 live
submission. The rapid paper tape converts fresh Phase-2 forecasts into
paper-only "would have traded" records, settles them directly from later public
observations, and mints negative capability crystals when a thesis loses. It
never calls private exchange endpoints and reports `private_orders=0`.

Start the safe profit lab in tmux:

```bash
scripts/launch_profit_lab_tmux.sh
tmux attach -t hivenance-profit-lab
```

Get a repeatable profitability snapshot without hand-written SQL:

```bash
./.venv-phase1/bin/python scripts/report_rapid_profit_lab.py --database data/swarm_data.db
```

Rapid paper now defaults to both `UP` and `DOWN` directions so the champion
scout can admit risk-off slices when the evidence supports them. To override
that direction set explicitly:

```bash
HIVENANCE_RAPID_DIRECTIONS=UP scripts/launch_profit_lab_tmux.sh
```

The tmux launcher now enables champion-scout paper admission by default. This
means fresh forecasts must be backed by positive settled slice evidence before
they receive a new paper slot. To run a deliberately broader control tape:

```bash
HIVENANCE_RAPID_CHAMPION_SCOUT=0 scripts/launch_profit_lab_tmux.sh
```

The first real rapid tape on August 5, 2026 opened 7 directional paper trades
from recent hypotheses and closed all 7 as losses: `0/7` wins, `-910.01 bps`
total net. A later UP-only run improved behavior but remained negative. The
latest local snapshot during the August 5 lab showed `28` closed paper trades,
`4` wins, `24` losses, `14.29%` win rate, and `-1563.12 bps` total net. This is
not profit evidence. It is useful falsification evidence. The only positive
recent scout pocket visible at that point was a WebCrypto market-context `DOWN`
slice, so the launcher now allows both directions by default instead of forcing
the weaker UP-only tape.

The rapid tape now applies explicit admission scar tissue:

- duplicate open exposure is blocked for the same `symbol x model x direction`
- fresh losing `symbol x model x direction` slices are cooled down
- Phase-2 negative capability crystals refuse repeatedly bad exact scopes
- model/direction pairs enter probation after enough negative closed evidence
- champion-scout mode prioritizes settled-positive `model x hypothesis x horizon x direction` slices
- stale symbols with missing post-target observations enter data-gap cooldown

This turns losses into selection pressure instead of letting the system repeat
the same mistake at full speed.

## Current truth and repaired-source merge

The repaired source archive `Hivenance-Phoenix-Repaired-Source.zip` contributed
a database-native truth reporter, offline pipeline mode, Linux packaging checks,
and clean release tooling. These were merged without replacing the newer rapid
paper tape, champion scout, DIO/Commons boundary, or BEAST crystal work.

Render the current authority state directly from SQLite:

```bash
./.venv-phase1/bin/python scripts/render_current_truth.py --database data/swarm_data.db --output CURRENT_TRUTH.json
```

For operational speed on the current large local database, this command defaults
to compact recent evidence and labels promotion authority as
`full_gate_recompute_required`. It is a fast truth/status path, not a shortcut
around exact gate recomputation. On August 5, 2026, after query-plan repair, it
completed against the `16.8 GB` local database in about `1.1s`.

Fast Phase-2 status without forcing settlement:

```bash
./.venv-phase1/bin/python scripts/run_phase2_hypotheses.py --database data/swarm_data.db --settle-only --report-only --once
```

That report-only path completed in about `0.44s` after replacing a bad compact
SQLite join with explicit primary-key forecast lookups. The exact settlement
backlog remains useful work, but it should be run intentionally rather than on
every UI/status heartbeat.

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

As of **Thursday, August 6, 2026**, `CURRENT_TRUTH.json` reports:

- **Overall state:** `READY_FOR_PHASE5_HUMAN_REVIEW`
- **Authority:** `RESEARCH_ONLY`
- **Live execution authorized:** `false`
- **Safety:** `CLEAN`
- **Real orders submitted:** `0`
- **Profit claim:** `SUPPORTED`, limited to the current research evidence and not a live-profit claim

The Phase 1 to Phase 4 pipeline is now clear:

- **Phase 1 observation:** `ALLOW`
- **Phase 2 hypotheses:** `ALLOW`
- **Phase 3 execution lab:** `ALLOW`
- **Phase 4 adversarial validation:** `ALLOW`
- **Phase 5 shadow flight:** `REFUSE`, intentionally, because the freeze is active but no shadow intents have settled yet

The current Phase-4 champion is a narrow execution slice:

```text
model_id=candidate_finrl_conservative_policy_proxy_v1
order_policy=passive_post_only
symbol=SOL/USD
direction=DOWN
```

The latest frozen Phase-4 run (`val-1786021737612-4e40fc3e`) evaluated `432`
candidates. The selected champion passed the configured candidate gates with:

- normal mean net: `30.16 bps`
- normal win rate: `0.80`
- normal samples: `10`
- bootstrap lower 95% mean: `20.65 bps`
- 1.5x cost-stress mean net: `6.54 bps`
- 2x cost-stress mean net: `-29.01 bps`, still above the configured catastrophic floor
- PBO estimate: `0.0286`
- real orders: `0`

The approved Phase-5 freeze is:

```text
freeze_id=e2bab35c306808bbe46a9cf62aaa870235daf4b268e77e47eaaabcedc5be752d
approved_by=Byron Bunt
model_id=candidate_finrl_conservative_policy_proxy_v1
order_policy=passive_post_only
symbol=SOL/USD
direction=DOWN
shadow_only=true
execution_eligible=false
```

The DSR diagnostic remains reported but advisory for this narrow slice because
the trial correction is dominated by sparse historical trials. It is not being
used as a hard blocker in the current frozen execution-slice court. This is
deliberate: the gate now tests whether the specific slice survived the configured
court, while Phase 5 is where shadow economics must prove fill behavior and cost
model accuracy.

The operational acceptance runner is configured for Phase 5 only:

```bash
./.venv-phase1/bin/python3 scripts/run_research_acceptance_pipeline.py \
  --exchange kraken \
  --offline \
  --once \
  --phase-timeout-sec 300
```

The configured default skips already-proven Phase 2 and Phase 3 gates and
does not refresh/replace the frozen Phase-4 court record. Explicit overrides are
still available:

```bash
python scripts/run_research_acceptance_pipeline.py --offline --phase3-only --once
python scripts/run_research_acceptance_pipeline.py --offline --phase4-only --once
python scripts/run_research_acceptance_pipeline.py --offline --phase5-only --once
```

This means the stack is no longer blocked before Phase 4. The next legitimate
boundary is Phase 5: freeze review, shadow intents, shadow settlement, fill
ratio, shadow net return, and cost-model error.

## Piece-by-piece score

These scores are an honest read of the current system state on **Thursday,
August 6, 2026**.

**Headline system score against its stated profit mission: 7.4/10.** The
increase is real: Phase 1 through Phase 4 now produce a supported post-cost
research edge for one exact execution slice. The score is still not higher
because Phase 5 shadow economics and Phase 6 canary evidence do not exist yet.

- architecture and authority separation: **9.2/10**
- safety and governance: **9.5/10**
- observation quality: **8.5/10**
- evidence lineage and reproducibility: **9.2/10**
- multi-system research orchestration: **8.8/10**
- hypothesis diversity: **7.8/10**
- demonstrated hypothesis edge: **6.5/10**
- execution realism: **8.3/10**
- validation rigor: **8.0/10**
- frontend and operator usability: **7.2/10**
- research-cycle throughput: **8.7/10**
- profit readiness: **6.4/10**
- overall as a governed research platform: **8.9/10**
- overall as a live profit machine today: **4.2/10**

Interpretation:

- The platform now has a full evidence path through Phase 4. That is the
  meaningful change from the previous score.
- The demonstrated edge score improved because the current Phase-4 champion is
  positive after modeled costs, positive under 1.5x cost stress, and has a
  positive bootstrap lower bound.
- The validation score is not perfect because the passing edge is narrow:
  one model, one order policy, one symbol, one direction, and a small normal
  sample count.
- The live-profit score remains low because no live canary has run and no
  shadow intent has settled. The freeze is active, but shadow/canary economics
  are still empty.
- In plain terms: this is now a **strong governed research platform with a
  narrow Phase-4-supported edge**, not yet a self-authorized live trading system.

## Proposed way forward

The next work should optimize Phase 5 economics, not reopen the Phase 1 to Phase
4 gates unless new evidence invalidates them.

### 1. Keep Phase 1 to Phase 4 unblocked

- Phase 2 and Phase 3 are frozen as passed for the current accepted evidence
  chain.
- The acceptance loop is configured to run Phase 5 shadow economics directly.
- Build verification now exercises the Phase-5-only path.
- Any future blocker before Phase 5 should be treated as a regression unless it
  reflects genuinely new contradictory evidence.

### 2. Maintain the approved Phase-5 freeze packet

- The approved freeze is exactly the current Phase-4 champion:
  `candidate_finrl_conservative_policy_proxy_v1 / passive_post_only / SOL/USD / DOWN`.
- Preserve the Phase-4 run id, dataset hash, config hash, candidate key, model
  id, order policy, symbol, direction, and stress metrics.
- Keep authority at `RESEARCH_ONLY`; Phase 5 is paper-only shadow flight.

### 3. Generate shadow economics

- Create venue-shaped shadow intents without submitting orders.
- Settle those intents against public market data.
- Measure fill ratio, modeled-vs-realistic cost error, shadow mean net, tail
  loss, stale-signal behavior, and passive-post-only missed-fill behavior.
- Do not let a paper intent become a live order.

### 4. Use canary only after shadow evidence

- Phase 6 remains locked until Phase 5 produces sufficient settled shadow
  evidence and a separate human approval exists.
- The first canary should still be tiny, isolated, one symbol, one order policy,
  one entry, hard loss limits, and automatic halt.
- A successful canary adds evidence; it does not authorize scaling.

### 5. Keep the economics falsifiable

- Track gross edge separately from fees, spread, slippage, latency, fill ratio,
  and missed fills.
- If Phase 5 fails, record the failure cause as reusable negative evidence
  instead of lowering gates retroactively.
- If Phase 5 passes, create a reviewed promotion packet before any canary
  discussion.

## What Is Actually Working

What is real today:

- Phase 1 is collecting market observations, ranking symbols, tagging tradability, and persisting durable snapshots.
- Phase 2 is generating frozen forecasts, settling them later, and building a real evidence ledger instead of hand-wavy backtests.
- Phase 3 is simulating execution under spread, slippage, latency, participation, and stress-policy assumptions.
- Phase 4 now has a passing narrow candidate rather than only a least-bad champion.
- Phase 5 has an active human-approved shadow-only freeze for that exact
  candidate.
- The desktop stack can display compact backend snapshots without hanging on the large SQLite store.

What is not real yet:

- there is no earned right to scale capital
- there is no credible unattended live-profit claim
- there is no settled Phase-5 shadow-economics record
- the current post-freeze public cycle produced no frozen-model shadow intent
  because the model abstained in the current market state
- there is no broad, repeatable, post-cost edge across the full candidate population

## Where The Bottleneck Is

The bottleneck has moved. It is no longer the Phase 2, Phase 3, or Phase 4 gate.
It is now the conversion from:

`robust simulated edge -> frozen shadow intent -> settled shadow economics -> approved canary`

The current weakest link is Phase 5:

- no settled shadow intents
- no shadow fill-ratio evidence
- no shadow cost-model error measurement
- no shadow net-return record

That means the system should currently be treated as a **Phase-4-cleared
research system waiting for Phase-5 shadow economics**, not as a live profit
engine.

## Profit Constitution

The stronger next direction for this repo is documented in:

- [`docs/DIO_PHOENIX_PROFIT_CONSTITUTION_2026-08-05.md`](docs/DIO_PHOENIX_PROFIT_CONSTITUTION_2026-08-05.md)
- [`docs/HIVENANCE_COMMONS_POOL_INTEGRATION_PLAN_2026-08-05.md`](docs/HIVENANCE_COMMONS_POOL_INTEGRATION_PLAN_2026-08-05.md)
- [`docs/STRATEGY_WORKER_PREDICTION_AUDIT_2026-08-05.md`](docs/STRATEGY_WORKER_PREDICTION_AUDIT_2026-08-05.md)

That document reframes the system around:

- abstention-first capital allocation
- deterministic eligibility before authority
- slice-level profitability by regime, symbol class, horizon, and execution policy
- capacity-aware scaling instead of naive profit chasing
- evidence-only learning feedback after live action

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
python scripts/run_phase4_validation.py
python scripts/run_research_acceptance_pipeline.py --offline --phase4-only --once
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

## Current evidence summary

The latest completed acceptance cycle on August 6, 2026 reported:

- Phase 1: `ALLOW`, with `3` runs, `3` healthy runs, `25` snapshots,
  `2` distinct snapshot buckets, and mean data quality `1.0`
- Phase 2: `ALLOW`, with `300` forecasts, `100` settled non-abstain forecasts,
  `14` distinct research snapshots, `46` slice posteriors, and `2` positive
  slice posteriors
- Phase 3: `ALLOW`, with `3,465` completed normal simulations, `2,224` slice
  posteriors, `3` positive normal slice posteriors, `0` incidents, and `0`
  symbol halts
- Phase 4: `ALLOW`, with `432` candidates, PBO estimate `0.0286`, and a passing
  SOL/USD downside passive-post-only champion
- Phase 5: `REFUSE`, with an active human-approved freeze but `0` settled shadow
  intents, `0` fill-ratio evidence, `0` cost-error evidence, and `0` real orders
- real orders submitted: `0`

The practical conclusion has changed: durable post-cost research edge is now
demonstrated for one narrow Phase-4 slice. Deployable edge is not yet
demonstrated because the post-freeze shadow campaign has not yet produced a
settled intent.

## Recent system additions

Recent work in this branch materially improved the research stack and cleared
the Phase 1 to Phase 4 evidence path:

- Restored the original CEX multi-horizon market-oracle thesis as a real
  Phase-2 federation model:
  - derives `1h`, `5h`, `24h`, `7d`, and `30d` context from durable
    `observation_snapshots`
  - carries horizon agreement, weighted move, spread/depth stability, and cost
    evidence in every forecast payload
  - remains proposal-only with `execution_eligible=false` and `orders_submitted=0`
- Added the source-fingerprinted VNS/CCE/Triune/polyphonic/Seraph/Sophia/Mandos
  synthesis challenger with proposal-only authority and tamper-evident receipts.
- Added the fast latest-observation synthesis audit.
- Repaired exact Commons ticket resolution and enforced quarantine across
  wrapped worker selections; all 69 stale FreqAI adoptions were revoked.

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
- Added frozen Phase-2 and Phase-3 pass controls for the current accepted
  evidence chain.
- Added Phase-4-only acceptance mode so the active loop optimizes the current
  remaining pre-shadow gate.
- Added Phase-5-only acceptance mode so the active loop now optimizes shadow
  economics without replacing the frozen Phase-4 court record.
- Narrowed Phase-4 candidate identity to the executable slice:
  `model_id x order_policy x symbol x direction`.
- Made sparse DSR correction advisory rather than a global blocker for the
  current narrow execution-slice court.
- Approved the current Phase-4 champion for Phase-5 shadow-only flight.
- Extended Phase-5 shadow intake to reject already expired forecasts and respect current time when selecting candidates.
- Extended Phase-5 shadow intent and settlement logic to support the frozen
  `DOWN` research slice directionally while keeping `execution_wired=false` and
  `real_orders_submitted=0`.
- Added Path A frozen-champion shadow admission: an abstaining Phase-2 row may
  create a paper-only Phase-5 intent only when its raw frozen-model utility
  matches the approved slice direction and clears the configured
  `phase5_frozen_shadow_min_utility` threshold. This lets shadow economics test
  the exact Phase-4 `SOL/USD DOWN` research slice without making it
  canary-compatible.
- Rejected stale Phase-5 Commons verifier packets whose subject digest
  reconstruction does not match the current Phase-5 ticket format, so invalid
  verifier receipts cannot create a false shadow contradiction.
- Improved Phase-4 validation sampling to use a more balanced per-candidate/per-scenario dataset slice.
- Upgraded the desktop validation page to surface champion, pass/fail summary, robustness, and top failure context.

## Honest Evaluation

This is **not yet a system I would trust to trade unattended for profit**, but
it is no longer stuck before the adversarial-validation boundary.

The strongest parts:

- governance and authority boundaries are better than most hobby or even semi-serious trading stacks
- observation capture is live, durable, and useful
- execution simulation is materially more realistic than a simple backtest-only workflow
- the platform now has enough structure to falsify bad ideas instead of merely generating them
- Phase 1 through Phase 4 now support one exact post-cost research edge

The weakest parts:

- the passing edge is narrow and sample-limited
- DSR remains weak as a global multiple-testing diagnostic for the current sparse
  trial set
- Phase 5 has a frozen shadow packet, but no settled shadow intents and no
  measured fill/cost error yet
- Path A will still abstain when the raw frozen-model utility points the wrong
  way; the latest public cycle pointed UP, so no DOWN shadow intent was created.
- profitability is demonstrated in the research court, not in shadow or live
  execution

My honest judgment:

- as a governed research platform: **8.9/10, strong**
- as a capital-preserving decision framework: **8.4/10, stronger**
- as a Phase-4 research-profit candidate: **7.4/10, credible but narrow**
- as a current live profit machine: **4.2/10, not ready**

Follow the measurable **Proposed way forward** above. Freeze the Phase-4
champion, run shadow economics, settle the paper-only intents, and only then
consider a human-approved canary. Do not unlock live capital merely because
Phase 4 passed; Phase 4 makes the candidate reviewable, while Phase 5 has to
prove the economics of behaving like a venue-shaped strategy.

See:

- `PHASE7_OPERATOR_GUIDE.md`
- `PHASE7_CHANGELOG.md`
- `PHASE7_VALIDATION_REPORT.md`
- `PHASE7_SYNTHETIC_GROWTH_REPORT.json`
