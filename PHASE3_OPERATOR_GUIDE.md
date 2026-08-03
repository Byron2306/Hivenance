# Hivenance Phoenix Phase 3: Execution Lab operator guide

## Purpose

Phase 3 converts settled Phase-2 forecasts into deterministic, execution-aware simulations. It asks
whether a forecast could survive venue rules, spread, fees, depth participation, latency, missed
fills, partial fills and infrastructure failure. It does not contact a private exchange endpoint and
cannot submit a real order.

## Safety contract

```yaml
phoenix_phase: 3
phase0_quarantine: true
dry_run: true
live_mode: false
auto_trading_enabled: false
onchain_enabled: false
phase3_execution_lab_enabled: true
public_bot_metrics_auto_promote: false
swarmguard_small_trade_bypass: false
hummingbot_sidecar_live_enabled: false
hummingbot_v2_leverage: 1
```

The Phase-3 module records:

- `execution_wired: false`
- `private_exchange_access: false`
- `live_eligible: false`
- `real_orders_submitted: 0`

The preflight rejects private execution imports and familiar order-submission method names inside the
Phase-3 research modules.

## Installation

```bash
python3 -m venv .venv-phase3
source .venv-phase3/bin/activate
python -m pip install -r requirements-phase3.txt
```

Validate the inherited safety chain and Phase-3 contract:

```bash
python scripts/phase0_preflight.py
python scripts/phase1_preflight.py
python scripts/phase2_preflight.py
python scripts/phase3_preflight.py
PYTHONPATH=. pytest -q
```

## Run a complete public-data cycle

This obtains public market observations, runs Phase-2 hypotheses, settles mature forecasts and
simulates eligible settled forecasts:

```bash
python scripts/run_phase3_execution_lab.py --once
```

Full JSON output:

```bash
python scripts/run_phase3_execution_lab.py --once --json
```

Continuous operation:

```bash
python scripts/run_phase3_execution_lab.py
```

An explicit public venue identifier can be supplied:

```bash
python scripts/run_phase3_execution_lab.py --exchange kraken --once
```

Public connectivity depends on the installed CCXT build and network access. No API credentials are
required for Phase 3.

## Replay settled Phase-2 forecasts only

```bash
python scripts/run_phase3_execution_lab.py --replay-only --once
```

This does not fetch market data. It consumes already persisted, settled, non-abstaining Phase-2
forecasts and the public entry observation attached to each forecast.

## Tournament design

Each forecast is tested under four execution policies:

1. `market`
2. `marketable_limit`
3. `passive_post_only`
4. `passive_then_chase`

Each policy is tested under five scenarios:

1. `normal`
2. `cost_1_5x`
3. `cost_2x`
4. `liquidity_stress`
5. `infrastructure_stress`

A fully processed forecast therefore produces 20 deterministic simulations. Simulation identifiers
are derived from forecast, policy, scenario and simulator version. Replaying the same evidence does
not duplicate simulations.

## Simulated order lifecycle

```text
CREATED
  -> VALIDATED
  -> PERSISTED
  -> SUBMITTED_SIMULATED
  -> ACKNOWLEDGED | UNKNOWN
  -> OPEN | PARTIALLY_FILLED | FILLED
  -> CLOSED | EXPIRED | REJECTED | RECONCILED
```

An unknown acknowledgement generates a critical incident, halts the simulated symbol and enters a
reconciliation path. Automatic recovery remains forbidden.

## Venue profile

Phase 3 begins with `kraken-research.v1`. It models conservative research defaults for:

- minimum notional and minimum quantity;
- price and quantity rounding;
- maker and taker fees;
- supported execution policies;
- spread and data-quality rejection gates.

The compact profile is not presented as live instrument metadata. Production precision, minimums,
fee tiers and status flags must later come from venue-native instrument feeds.

## Risk sizing

The simulator converts forecast risk into a bounded notional using:

- simulated equity;
- per-trade risk fraction;
- stop-distance estimate;
- experimental sleeve fraction;
- maximum notional;
- maximum depth participation;
- venue minimums.

DOWN forecasts remain synthetic research comparisons. They are marked `spot_executable: false` and
do not imply short, margin or derivative capability.

## Cost attribution

Every simulation preserves a cost waterfall containing:

- forecast gross opportunity;
- observed market movement;
- entry and exit spread;
- entry and exit impact;
- entry and exit latency drift;
- maker or taker fees;
- missed-fill opportunity cost;
- stop slippage;
- total cost and net result.

## Durable projections

Phase 3 adds:

- `simulation_runs`
- `simulated_order_intents`
- `simulated_orders`
- `simulated_order_events`
- `simulated_fills`
- `simulated_positions`
- `simulated_cost_attribution`
- `simulation_incidents`

These are separate from the existing live `orders` table. The simulator never mutates the live table.

## Desktop console

The Electron console includes an **Execution Lab** page with:

- simulation health and safety invariants;
- policy and scenario scorecards;
- completed, rejected, expired and partial-fill counts;
- cost and slippage attribution;
- recent simulated order lifecycles;
- permanent zero-real-order status.

## Phase-4 review gate

The default Phase-3 gate requires:

- at least 100 completed normal simulations;
- positive mean net result under normal costs;
- positive mean net result under 1.5x costs;
- a non-catastrophic result under 2x costs;
- zero execution-wiring violations;
- zero real orders;
- zero automatic recoveries;
- human review.

Passing the gate does not enable paper or live authority. Phase 4 performs adversarial statistical
validation, holdouts, perturbation and overfitting analysis.

## Fidelity boundary

Current simulations are explicitly marked `OBSERVATION_PROXY`. They use persisted public
observation spread and depth summaries rather than a fully reconstructed exchange event stream.
Consequently:

- queue position is probabilistic and deterministic by seed;
- partial fills are conservative models rather than historical venue fills;
- candle or snapshot evidence is not treated as true L2 replay;
- private account state and venue acknowledgements are never queried.

A future fidelity upgrade should add sequence-checked L2 snapshots and deltas, public trades and
venue-native instrument metadata before shadow operation.
