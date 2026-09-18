# Phase 5 Operator Guide: Public-Market Shadow Flight

## Purpose

Phase 5 walks a frozen Phase-4 champion beside live public market data without allowing it to touch
capital. Hivenance creates the exact order-shaped record it would have wanted to submit and later
measures the public-market outcome.

## 1. Validate the package

```bash
python scripts/phase0_preflight.py
python scripts/phase1_preflight.py
python scripts/phase2_preflight.py
python scripts/phase3_preflight.py
python scripts/phase4_preflight.py
python scripts/phase5_preflight.py
python -m pytest -q
```

## 2. Accumulate genuine Phase-4 evidence

Run Phases 1 through 4 until `ready_for_phase5_review=true`. Inspect the candidate report, rejected
alternatives, concentration, walk-forward folds, holdouts, cost stress, DSR and PBO diagnostics.

## 3. Approve one frozen champion

```bash
python scripts/run_phase5_shadow_flight.py \
  --approve-current-champion \
  --approved-by "Byron Bunt"
```

The command refuses approval when the latest Phase-4 gate is closed, the champion is incomplete or
the selected candidate is a baseline.

Approval freezes the full strategy and shadow-execution configuration. It is not live-trading
approval.

## 4. Run shadow flight

```bash
python scripts/run_phase5_shadow_flight.py
```

The runner uses an unauthenticated public CCXT client. No API key is required or read.

Offline/persisted mode:

```bash
python scripts/run_phase5_shadow_flight.py --shadow-only --once --json
```

## 5. Monitor the dashboard

The Shadow Flight page displays:

- frozen champion and reviewer;
- never-transmitted venue-shaped intents;
- hypothetical settlement count and fill ratio;
- mean net result and cost-model error;
- distinct UTC evidence days;
- Phase-6 review failures;
- permanent zero transmission and zero real-order status.

## 6. Parameter changes

Do not tune the model during a shadow campaign. Any frozen configuration change produces
`LOCKED: frozen_parameter_drift` and no new intents. Re-run Phase 4 and create a new human approval
for the new candidate/configuration.

## 7. Revoke immediately when needed

```bash
python scripts/run_phase5_shadow_flight.py \
  --revoke-approval \
  --reason "unexpected data or model behaviour"
```

Historical evidence remains immutable.

## 8. Phase-6 review gate

Initial engineering gate:

- at least 100 settled shadow intents;
- at least 30 distinct UTC evidence days;
- hypothetical fill ratio at least 50%;
- cost-model mean absolute error no more than 20 bps;
- positive mean net outcome after proxy costs;
- unchanged frozen configuration;
- zero transmission attempts;
- zero real orders;
- explicit human review.

Passing this gate does not activate execution. Phase 6 must separately introduce a tiny live canary,
durable live OMS/reconciliation and explicit capital authorization.
