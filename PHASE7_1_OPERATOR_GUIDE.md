# Hivenance Phoenix Phase 7.1 Operator Guide

Phase 7.1 reconciles the heavy integrations with the Phoenix authority chain.

## Authority

- External bots, ML, marketplace, Config Agent, Event Spine, and execution parity have no live-order, promotion, resume, or scaling authority.
- Phase 6 is the only live-order authority.
- Phase 7 is the only capital-stage authority.
- The ordinary `main.py` coordinator is permanently research-only.

## Validation

```bash
python scripts/phase7_1_preflight.py
python -m pytest -q
```

## Read the authority map

From the local UI/API:

```text
GET /phoenix/authority.json
GET /architecture/plan.json
```

## External backtests

External results may be imported, normalized, and inspected. They are always marked `UNVALIDATED_IMPORT` and must enter Phoenix at Phase 2.

## Configuration

The Config Agent can update research and diagnostic settings. It rejects `ARM LIVE`, live mode, dry-run disablement, on-chain enablement, automatic promotion, live sidecars, quote placement, autonomy, governance bypasses, and leverage above 1x. Unsafe rollback snapshots are also rejected.

## Hummingbot

The integrated lifecycle surface is planning and monitoring only. It cannot create, retry, or close a live executor through the ordinary coordinator.

## Legacy promotion script

`scripts/promote_symbols.py` now produces research candidate summaries only. It never writes `tiny_live` or `normal` stages.
