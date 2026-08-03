# Hivenance Phoenix Phase 5 Changelog

## Added

- `ShadowFlightAgent`, a public-market-only Phase-5 orchestrator.
- Human-approved model freezes tied to the exact Phase-4 run, champion, dataset and configuration.
- CLI approval and revocation commands.
- Venue-shaped `ShadowOrderIntent` records with a permanent `NEVER_TRANSMITTED` state.
- Delayed settlement against later public observations.
- Market, marketable-limit, passive-post-only and passive-then-chase shadow fill proxies.
- Predicted-versus-observed cost parity metrics.
- Thirty-day, 100-settlement Phase-6 review gate.
- Parameter drift, champion drift and Phase-4 readiness revocation locks.
- Four durable SQLite projections:
  - `phase5_model_freezes`
  - `phase5_shadow_runs`
  - `phase5_shadow_intents`
  - `phase5_shadow_settlements`
- Shadow Flight API endpoint and Electron dashboard.
- Phase-5 preflight, operator guide, validation report and automated tests.

## Safety changes

- Phase 5 contains no private exchange client and no transmission method.
- Credentials are never loaded by the Phase-5 runner.
- Only UP forecasts can produce spot shadow intents. DOWN forecasts remain research evidence.
- Every intent and settlement records zero private calls, zero transmissions and zero real orders.
- A changed frozen parameter halts new shadow generation.
- Human approval can be revoked without altering historical evidence.

## Honest fidelity boundary

Shadow fills use continuing public snapshots rather than authenticated venue acknowledgements,
private order updates or queue-accurate L2 reconstruction. They are evidence about forecast/execution
parity, not proof of actual fills or profitability.
