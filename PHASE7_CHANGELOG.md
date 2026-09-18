# Hivenance Phoenix Phase 7 Changelog

## Release

**Phase:** 7  
**Name:** Controlled Growth Governor  
**Date:** 2026-08-01

## Added

- A separate Phase-7 growth-governance plane that does not own exchange transport.
- Five monotonic operating stages:
  - CANARY: USD 5, one symbol
  - EMBER: USD 7.50, one symbol
  - FLAME: USD 10, two symbols
  - WING: USD 15, two symbols
  - CROWN: USD 20, three symbols
- One open order and one open position remain the maximum at every stage.
- A fresh evidence block is required for every stage:
  - at least 50 new reconciled round trips,
  - at least 14 distinct live UTC days,
  - positive realised P&L,
  - profit-factor, drawdown, loss-rate, rejection-rate and slippage gates,
  - no unknown orders, unresolved incidents or open positions.
- Immutable growth proposals with evidence and configuration hashes.
- A default 24-hour proposal cooling-off period.
- Temporary human approvals with an exact risk acknowledgement.
- A separate `HIVENANCE_PHASE7_CONTROLLED_GROWTH=YES` activation interlock.
- Rechecks at proposal, approval and activation time. Stale proposals are rejected.
- Automatic one-stage demotion on:
  - unknown order state,
  - unresolved incident,
  - drawdown breach,
  - rejection-rate breach,
  - slippage breach.
- No automatic recovery. Human recovery requires:
  - all incidents resolved,
  - all unknown orders reconciled,
  - no open positions or orders,
  - a fresh CLEAN Phase-6 reconciliation,
  - exact recovery acknowledgement,
  - Phase-7 environment interlock.
- The existing Phase-6 one-entry human lease remains mandatory for every new entry.
- A read-only desktop **Growth Governor** page.
- Durable Phase-7 SQLite projections:
  - `phase7_growth_state`
  - `phase7_growth_proposals`
  - `phase7_growth_approvals`
  - `phase7_growth_windows`
  - `phase7_growth_incidents`
  - `phase7_growth_audit`
- Standalone operator tools:
  - `scripts/run_phase7_growth.py`
  - `scripts/phase7_preflight.py`
  - `scripts/phase7_synthetic_soak.py`

## Preserved safety boundaries

- Kraken spot only.
- Leverage fixed at 1×.
- No DEX execution.
- No automatic strategy promotion.
- No automatic capital scaling.
- No desktop proposal, approval, activation, execution, recovery or scaling controls.
- Growth authority remains operator-process-only.
- The legacy `orders` and `fills` tables remain outside the Phase-7 authority path.
- Phase 7 ships with both stage activation and live submission disabled.

## Known fidelity boundary

Phase 7 governs capital envelopes. It does not improve the current Phase-6 venue execution fidelity. Protective exits remain supervised by the local operator process rather than guaranteed venue-native contingent orders. The default growth ceiling therefore remains USD 20 with one open position.
