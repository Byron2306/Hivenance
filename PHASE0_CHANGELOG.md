# Hivenance Phoenix, Phase 0 changelog

## Safety boundary

- Added `phase0_quarantine`, enforced in configuration and at process startup.
- Closed the `dry_run=false` plus `live_mode=false` live-order loophole.
- Removed the branch that disabled the kill switch and performance monitoring in live mode.
- Unknown exchanges now fail closed instead of falling through to Binance.
- Disabled auto-trading, volatility harvesting, live DEX, automatic promotion, small-trade bypass,
  Hummingbot live execution, leverage, autonomous coin switching, market-making placement,
  and OpenClaw autonomy in every shipped profile.
- Added runtime config guards so the UI cannot re-enable quarantined controls.

## Security containment

- Removed exchange credentials, backup credentials, and the reusable Fernet key.
- Added environment-variable credential loading, examples, and Git exclusions.
- Bound the UI and Docker-exposed services to loopback.
- Replaced reflected CORS with a fixed local-origin allowlist.
- Made exchange secrets write-only in the configuration page.
- Removed the Docker socket mount and Docker CLI from the trading container.
- Removed `CHANGE_ME` secret fallbacks; the local launcher creates an ephemeral secret,
  while Docker requires an explicit local `.env` value.

## Ember strategy quarantine

- Added a typed, observation-only volatility-breakout scaffold.
- Added explicit volatility horizons, universe filters, risk envelope, and evidence gates.
- The scaffold always abstains and is deliberately disconnected from execution.

## Packaging and verification

- Normalized the Electron client under `desktop-ui/`.
- Restored root `main.py`, `run_ui_server.py`, and `requirements.txt`.
- Added a Phase-0 preflight and focused tests.
