# Hivenance Ember Sleeve: Phoenix Research Pipeline

## Phases 1 through 4

The earlier phases observe public markets, generate independent forecasts, simulate execution and
subject candidate model-policy pairs to adversarial validation. None of them can submit an order.

## Phase 5: Public-Market Shadow Flight

Phase 5 accepts exactly one human-approved Phase-4 champion and freezes:

- validator run ID and evidence dataset hash;
- candidate key, primary model and execution policy;
- all strategy, sizing and shadow-execution parameters;
- reviewer identity and approval timestamp.

Fresh non-abstaining forecasts from that frozen model may become complete shadow intents containing
venue, symbol, side, policy, order type, quantity, notional, reference/limit price, horizon, risk
budget and cost forecast. These records are marked `NEVER_TRANSMITTED` and the Phase-5 modules expose
no private exchange or order-submission interface.

Later public observations settle each shadow intent using an explicitly labeled snapshot proxy. The
scorecard compares predicted cost with observed proxy cost, fill ratio, forward net return and data
quality across distinct UTC evidence days.

Any parameter change, champion change, validation-run change, revoked approval or readiness failure
locks shadow generation.

Permanent invariants:

- `private_exchange_access = false`
- `execution_wired = false`
- `transmission_attempts = 0`
- `real_orders_submitted = 0`
- `live_eligible = false`
- `human_review_required = true`
- automatic promotion and automatic recovery are forbidden
