# Hivenance Phoenix Phase 7.1 Change Log

## Integration Reconciliation

- Added a single `PhoenixAuthorityGuard` for all legacy integrations.
- Declared Phase 6 the sole live-order authority and Phase 7 the sole scaling authority.
- Retired the legacy `ARM LIVE` configuration path.
- Added safe-rollback validation so old snapshots cannot restore live, on-chain, auto-promotion, quote-placement, autonomy, bypass, or leveraged settings.
- Converted external evidence verdicts into `UNVALIDATED_IMPORT` records requiring Phoenix Phase 2.
- Removed public-bot worker-weight mutation and all legacy `tiny_live` promotion writes.
- Converted the old symbol promotion script into a research evidence summarizer.
- Restricted Hummingbot lifecycle controls to plan/monitor/list/stop semantics.
- Converted ML readiness to `phoenix_phase2_candidate_ready` with no promotion authority.
- Converted execution parity into a diagnostic-only model-versus-reality auditor.
- Kept signal marketplace rewards simulated, sandboxed, and without promotion or scaling authority.
- Expanded Event Spine correlation identifiers across observations, forecasts, simulations, validation, shadow, canary, fills, approvals, proposals, and incidents.
- Added a read-only `/phoenix/authority.json` endpoint.
- Added Phase 7.1 preflight and authority-isolation tests.
