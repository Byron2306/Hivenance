# Phoenix Relative-Value Laboratory — Phase 1 Public Microstructure Evidence

**Status:** IMPLEMENTED, runtime verification pending  
**Authority:** public market research only

## Objective

Collect richer public-market evidence so Phoenix can reason about *why* a pair moved, not merely that it moved.

## Implemented evidence

The Phase 1 observer records, per symbol:

- best bid / ask;
- mid;
- spread bps;
- displayed depth inside 5 / 10 / 25 bps;
- 25-bps book imbalance;
- sequential best-quote OFI proxy;
- public trade-side buy/sell notional;
- aggressor-flow imbalance proxy;
- trade count;
- trade intensity;
- sequential depth recovery/depletion;
- data quality;
- explicit source/availability notes.

## Fidelity labels

The observer does **not** claim full exchange message-level order flow.

`quote_ofi_proxy` is derived from sequential best-price/size changes.

Trade-side evidence uses the side field exposed by the public Kraken Trades endpoint. It is treated as public trade-flow evidence, not privileged matching-engine truth.

## Public endpoints

- `AssetPairs`
- `Depth`
- `Trades`

No private endpoint is used.

No API key, secret, wallet or order method is present.

## Persistence

Default database:

`data/relative_value_microstructure.db`

Tables:

- `relative_value_microstructure_runs`
- `relative_value_microstructure_snapshots`

The raw normalized snapshot is retained as JSON alongside queryable scalar columns.

## Runtime

```bash
python scripts/run_relative_value_microstructure_observer.py \
  --duration-sec 900 \
  --interval-sec 15
```

Report latest run:

```bash
python scripts/report_relative_value_microstructure.py
```

The minimum interval enforced by the script is 5 seconds to avoid pretending a REST polling loop is a tick feed.

## Known limitations

- REST polling is not message-level market data.
- Depth is a sampled public book, not queue-position evidence.
- Between-poll events can be missed.
- Trade-side semantics are venue-provided and should remain provenance-labelled.
- Refill/depletion is observed between snapshots, not reconstructed from individual order events.
- Latency from the user's network is not yet separately timestamped.
- Direct pair route existence is handled by the pair/route layer, not this symbol observer.

A later websocket collector may improve temporal fidelity, but it must preserve this schema and authority boundary.

## Phase 1 acceptance

- [x] public-only feed
- [x] bid/ask and spread
- [x] 5/10/25 bps displayed depth
- [x] quote OFI proxy
- [x] public trade-flow evidence
- [x] intensity
- [x] depth recovery/depletion
- [x] SQLite persistence
- [x] reporter
- [x] data-quality and fidelity notes
- [x] no execution authority
- [ ] local runtime observation confirmed
- [ ] local pytest confirmed

Phase 2 pair mathematics may proceed while runtime verification is pending because it is deterministic and separately testable, but no empirical claim should cite Phase 1 until real observations are collected.
