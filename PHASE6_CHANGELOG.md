# Hivenance Phoenix Phase 6 Changelog

**Release:** Tiny Live Canary  
**Date:** 2026-07-31

## Added

### Isolated canary authority plane

- Added `strategies/volatility_breakout/canary_models.py`.
- Added `strategies/volatility_breakout/canary_store.py`.
- Added `strategies/volatility_breakout/canary_lab.py`.
- Added `strategies/volatility_breakout/kraken_canary.py`.
- Added standalone operator `scripts/run_phase6_canary.py`.
- Added Phase-6 profile and typed configuration fields.
- Added a deterministic fake-exchange safety campaign.

The regular Hivenance coordinator does not construct `TinyLiveCanary` and has no private Kraken
client. It can read the Phase-6 evidence projections only.

### Human authority contract

- Exact live-risk acknowledgement required.
- Approval is bound to the Phase-5 frozen champion and its configuration hash.
- Approval lease is short-lived.
- Exactly one entry is permitted per approval.
- Approval cannot authorize leverage or automatic scaling.
- Configuration or Phase-5 freeze drift causes HALT.

### Two-key live interlock

Live entry requires all of the following:

1. `--live` on the dedicated operator process.
2. A local profile with `phase6_live_submission_enabled: true`.
3. `HIVENANCE_PHASE6_LIVE_SUBMISSION=YES` in the environment.
4. A currently active human approval.
5. Environment-only Kraken credentials.
6. Clean startup reconciliation.

### Kraken canary adapter

The narrow client implements only the endpoints needed for:

- system status,
- instrument metadata,
- API-key permission inspection,
- balances,
- open-order and order-state reconciliation,
- validate-only AddOrder,
- AddOrder and cancellation,
- Cancel All Orders After X dead-man protection.

No deposit, withdrawal, account-transfer, earn or funding endpoint is implemented.

### Order and position truth

Added dedicated SQLite projections for:

- canary state,
- approvals,
- runs,
- intents,
- orders,
- positions,
- incidents,
- reconciliations,
- dead-man heartbeats.

Phase-6 does not mutate the legacy `orders` or `fills` tables.

### Safety semantics

- Unknown submission outcome causes immediate HALT.
- Unknown reconciliation state causes HALT and no retry.
- Manual HALT persists across clean reconciliations.
- UTC-day realised-loss ceiling blocks new entries.
- Active order and position caps are enforced.
- API-key permissions must be explicitly visible and must include order and query authority.
- Keys exposing withdrawal, transfer or earn-funds permissions are rejected.
- External open orders are rejected when isolated-account mode is enabled.
- Every live AddOrder is preceded by validate-only AddOrder.
- IOC marketable limits are used instead of unrestricted market orders.
- Deterministic `hv6...` client order IDs are persisted before submission.
- Live single-cycle mode is forbidden.
- Operator shutdown attempts to cancel pending orders and records HALT or EXIT_ONLY.

### Read-only desktop flight deck

Added `/canary.json` and a **Tiny Canary** desktop page showing:

- state and halt reason,
- approvals,
- orders and fills,
- positions,
- reconciliation state,
- incidents,
- completed round trips,
- Phase-7 review readiness.

The endpoint is GET-only. The page contains no live authority controls and never reveals the
environment interlock or credentials.

## Corrected during the furnace

- Fixed the ambiguous-submit path so subsequent cycles remain HALTED rather than appearing merely
  pending.
- Closed a persistent-state gap where manual HALT could otherwise have been followed by a new
  entry after a clean reconciliation.
- Converted the configured daily-loss limit from decorative configuration into an enforced entry
  gate.
- Made unavailable API-key permission metadata fail closed.

## Deliberately not included

- Automatic Phase-7 promotion or scaling.
- Leverage, margin, futures or DEX execution.
- Multi-venue live routing.
- Desktop arming or recovery.
- Withdrawal or transfer APIs.
- Claims of live Kraken validation or profitability.
