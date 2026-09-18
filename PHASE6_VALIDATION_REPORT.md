# Hivenance Phoenix Phase 6 Validation Report

**Release:** Tiny Live Canary  
**Date:** 2026-07-31  
**Validation scope:** source structure, safety contracts, deterministic fake-exchange integration,
persistence, static syntax, package hygiene and full Phase 0–6 regression lineage.

## Executive result

```text
RESULT: PASS
SHIPPING STATE: LIVE-CAPABLE BUT DISARMED
REAL EXCHANGE ORDERS SUBMITTED DURING VALIDATION: 0
PRIVATE KRAKEN REQUESTS DURING VALIDATION: 0
AUTOMATIC SCALING: FALSE
LEVERAGE: 1x
```

This report validates engineering behaviour. It does not validate strategy profitability, live
Kraken connectivity, venue fill quality or investment suitability.

## Full lineage

```text
Phase 0 preflight: PASS
Phase 1 preflight: PASS
Phase 2 preflight: PASS
Phase 3 preflight: PASS
Phase 4 preflight: PASS
Phase 5 preflight: PASS
Phase 6 preflight: PASS
```

## Automated tests

```text
38 passed
0 failed
```

The Phase-6 tests cover:

- no approval means no private order,
- validate-only mode performs no submission,
- one-entry approval consumption,
- entry reconciliation and position creation,
- target-triggered exit and round-trip closure,
- ambiguous submission timeout causes HALT,
- ambiguous submission is never retried,
- non-isolated account/open external order rejection,
- manual HALT persists after clean reconciliation,
- daily realised-loss limit blocks the next entry,
- API-key permissions must be explicitly visible,
- forbidden funding permissions fail closed,
- legacy order tables remain untouched.

## Deterministic fake-exchange control campaign

The campaign used an in-memory Kraken double and temporary SQLite databases. It created no network
socket and loaded no credentials.

```text
Requested round trips:                60
Completed reconciled round trips:     60
One-entry approvals:                  60
Phase-6 order records:               120
Validate-only calls:                 120
Fake AddOrder calls:                 120
Dead-man refreshes:                  120
Reconciliation records:              180
Open positions after campaign:         0
Unknown orders after campaign:         0
Unresolved incidents after campaign:   0
Legacy orders rows:                     0
Legacy fills rows:                      0
Automatic scaling:                  false
Phase-7 review readiness:            true
Execution scale authorized:         false
```

The synthetic price path was deliberately favourable so the **passing control path** could be
exercised. Its P&L is not market evidence and must not be used to justify live operation or scaling.

## Ambiguity sabotage

A separate fake exchange threw a timeout after the first submission attempt.

```text
First cycle:                   HALTED
Second cycle:                  HALTED
AddOrder attempts:             1
Unknown local order:           1
Automatic retry:               0
Legacy order mutations:        0
Human review required:       true
```

This confirms that uncertain submission does not become an optimistic retry.

## Safety contract checks

- The ordinary coordinator never constructs `TinyLiveCanary`.
- The desktop API is GET-only and cannot approve, arm, submit, scale, resume or recover.
- Environment credentials are never returned through snapshots.
- Live entry requires CLI flag, local configuration switch, environment interlock and active human
  approval.
- Live `--once` mode is forbidden.
- Each approval permits exactly one entry.
- Default maximum notional is USD 5.
- Default allowlist contains only ETH/USD.
- Maximum open Phase-6 orders and positions are both one.
- API permission metadata fails closed when absent.
- Withdraw, transfer and earn-funds permissions are rejected.
- AddOrder validate-only runs before actual submission.
- Unknown order state produces persistent HALT.
- Manual HALT cannot be cleared by a clean reconciliation.
- UTC-day realised-loss ceiling is enforced before entry.
- Operator shutdown attempts to cancel pending orders and records `EXIT_ONLY` when filled inventory
  remains.

## Static and structural checks

```text
Python compilation:                 PASS
Electron main syntax:               PASS
Electron preload syntax:            PASS
Renderer JavaScript syntax:         PASS
Linux launcher syntax:              PASS
HTML parsing:                        PASS
YAML parsing:                        PASS
JSON parsing:                        PASS
Typed Config constructor parity:    358 / 358
Credential-literal scan:            PASS
Forbidden runtime artifacts:        NONE
```

The release tree contains no populated `.env`, API-key file, reusable encryption key, SQLite
runtime database, Python cache or Node dependency directory.

## Honest residual-risk boundary

Phase 6 currently uses REST reconciliation and local public-price supervision. The dead-man switch
cancels pending orders but does not liquidate a filled spot balance. A hard operator-machine failure
can therefore leave the capped spot holding in the isolated account. The release mitigates this by
forbidding live single-cycle operation, requiring continuous supervision, limiting the entry to USD
5 and prohibiting leverage.

Before any cap increase, the next hardening target should be a verified private execution stream and
venue-native protective exit behaviour.

## Claims deliberately not made

- No live Kraken request was made.
- No real order or fill was produced.
- No real API key was loaded.
- No genuine Phase-5 market campaign was promoted.
- No profitability or expected-return claim is made.
- No Phase-7 scaling is authorized.

## Fresh-archive verification

The release archive was extracted into a new directory with no reused runtime state. The extracted
copy passed:

```text
Archive compression test:            PASS
Fresh Phase 0–6 preflights:           PASS
Fresh automated tests:                38 passed
Fresh Electron syntax:                PASS
Fresh shell syntax:                   PASS
Fresh Config parity:                  358 / 358
Fresh HTML/YAML/JSON parsing:          PASS
Packaged forbidden files:             NONE
Archive entries inspected:            234
```
