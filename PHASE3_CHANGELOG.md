# Hivenance Phoenix Phase 3 changelog

**Release:** Phoenix Phase 3, Execution Lab  
**Date:** 2026-07-31

## Added

### Execution-aware simulator

- Added deterministic simulation of settled Phase-2 forecasts.
- Added four execution policies: market, marketable limit, passive post-only and passive-then-chase.
- Added five stress scenarios: normal, 1.5x cost, 2x cost, liquidity stress and infrastructure stress.
- Added conservative risk-budget sizing and depth-participation caps.
- Added venue-profile validation for minimum notional, precision, fees and spread gates.
- Added explicit research-only treatment of DOWN forecasts in the spot-only sleeve.

### Order truth model

- Added simulated intent persistence before submission state.
- Added canonical simulated order events, partial fills, expiry, rejection and reconciliation.
- Added deterministic simulation and intent identifiers.
- Added unknown-order incidents with symbol halt and no automatic recovery.
- Added fill provenance and execution-fidelity labels.

### Economics and diagnostics

- Added fees, spread, impact, latency, missed-fill opportunity and stop-slippage attribution.
- Added policy/scenario execution scorecards.
- Added Phase-4 readiness review logic.
- Added queue advancement so completed 20-scenario tournaments do not starve older forecasts.

### Persistence

Added independent SQLite projections:

- `simulation_runs`
- `simulated_order_intents`
- `simulated_orders`
- `simulated_order_events`
- `simulated_fills`
- `simulated_positions`
- `simulated_cost_attribution`
- `simulation_incidents`

Persistence rejects any Phase-3 row claiming live wiring or real submitted orders. The existing live
`orders` table is not used by the simulator.

### Runtime and UI

- Added `ExecutionLabAgent` and coordinator integration.
- Added `scripts/run_phase3_execution_lab.py` with public-cycle and replay-only modes.
- Added `scripts/phase3_preflight.py`.
- Added `config/volatility_breakout_phase3.yaml` and Phase-3 settings.
- Added `/execution_lab.json` UI endpoint.
- Added an Electron **Execution Lab** view.

### Tests

Added deterministic, safety and persistence tests for:

- repeatable simulation results;
- zero private execution and zero live orders;
- synthetic DOWN treatment;
- passive-order expiry without fabricated fills;
- idempotent persistence;
- a complete 20-simulation tournament;
- candidate queue advancement after completed tournaments.

## Changed

- Advanced all supplied runtime profiles to `phoenix_phase: 3` while retaining Phase-0 quarantine.
- Phase-2 preflight now accepts later Phoenix phases while preserving its safety checks.
- The coordinator starts Phase 3 ahead of the Phase-2 and Phase-1 background loops when enabled.
- Datastore errors now roll back failed Phase-3 persistence transactions.

## Preserved safety invariants

- dry run enabled;
- live mode disabled;
- auto-trading disabled;
- on-chain execution disabled;
- automatic promotion disabled;
- small-trade bypass disabled;
- leverage fixed to 1x;
- private exchange access absent from Phase-3 modules;
- real submitted order count fixed at zero.

## Known boundaries

- Fill fidelity is `OBSERVATION_PROXY`, not sequence-accurate L2 replay.
- Venue constraints are versioned conservative research defaults, not live instrument metadata.
- The artifact environment did not perform a live public Kraken fetch.
- Phase 3 makes no profitability or production-execution claim.
