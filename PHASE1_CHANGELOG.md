# Hivenance Phoenix, Phase 1 changelog

## Observation Swarm

- Added a dedicated public-market observation agent that runs independently of execution.
- Added venue-native universe discovery, active spot-market filtering, and configurable quote assets.
- Added explicit 1-minute volatility horizons, volume z-scores, L2 spread, depth within 25 bps,
  book-imbalance proxy, candle continuity, freshness, latency, and data-quality scoring.
- Added ranked observation eligibility while hard-coding execution eligibility to false.
- Added deterministic dataset hashes and observation run identifiers.

## Durable evidence

- Added a standalone public-only observer runner and minimal Phase-1 dependency manifest.
- Added a seven-distinct-observation-day readiness gate that can recommend Phase-2 review but never execution.

- Added SQLite observation-run and per-symbol snapshot projections.
- Added observation history/query helpers and `/observation.json` API exposure.
- Added observation status to coordinator heartbeats and the integration-plane snapshot.

## Truth corrections

- Corrected average-volume handling so volume arrays are used rather than closing prices.
- Removed the fake neutral sentiment value; unavailable sentiment now remains `None`.
- Preserved Phase-0 quarantine, disabled automatic promotion, disabled small-trade bypass,
  and retained 1x/no-live/no-on-chain safety constraints.

## Verification

- Added deterministic fake-venue tests for universe discovery, quality scoring, persistence,
  execution quarantine, unavailable features, and safety-policy continuity.
