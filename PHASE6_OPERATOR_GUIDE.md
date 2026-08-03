# Hivenance Phoenix Phase 6 Operator Guide

## 1. What Phase 6 is

Phase 6 is a **tiny, supervised Kraken spot canary**. It is the first phase capable of submitting a
real order, but the release ships disarmed and cannot be activated from the ordinary coordinator or
desktop application.

Default envelope:

```text
Venue: Kraken Spot
Symbol: ETH/USD
Maximum entry notional: USD 5
Maximum entries per approval: 1
Maximum open canary orders: 1
Maximum open canary positions: 1
Leverage: 1x
On-chain execution: disabled
Automatic scaling: disabled
Daily realised-loss halt: USD 1
```

These are engineering constraints, not a statement that trading is safe or profitable.

## 2. Non-negotiable prerequisites

Do not arm Phase 6 unless all of these are true:

1. Phase 5 has accumulated genuine public-market evidence and reports
   `ready_for_phase6_review=true`.
2. The frozen champion and its parameters have been reviewed by a human.
3. A dedicated canary Kraken account or otherwise isolated account context is being used, with no
   manual or unrelated open orders.
4. The API key has only the minimum trading/query permissions required by the canary.
5. Withdrawal, account-transfer and earn-funds permissions are disabled.
6. The account contains only the tiny quote balance you deliberately accept placing at risk.
7. The machine clock, network and storage are healthy.
8. The operator can supervise the process until the position is fully closed and reconciled.

Phase 6 checks visible key permissions and rejects forbidden funding permissions, but account
isolation is also an operator responsibility. Do not place a canary key on your main trading account.

## 3. Install and validate

```bash
python3 -m venv .venv-phase6
source .venv-phase6/bin/activate
python -m pip install -r requirements-phase6.txt

python scripts/phase0_preflight.py
python scripts/phase1_preflight.py
python scripts/phase2_preflight.py
python scripts/phase3_preflight.py
python scripts/phase4_preflight.py
python scripts/phase5_preflight.py
python scripts/phase6_preflight.py
python -m pytest -q
```

Inspect persisted status without credentials:

```bash
python scripts/run_phase6_canary.py --status
```

## 4. Create a local live profile

Never edit the shipped disarmed profile in place.

```bash
cp config/volatility_breakout_phase6.yaml \
   config/volatility_breakout_phase6.live.local.yaml
```

Change only:

```yaml
phase6_live_submission_enabled: true
```

Keep the following unchanged for the first canary:

```yaml
phase6_allowed_symbols:
  - ETH/USD
phase6_max_notional_usd: 5.0
phase6_max_entry_orders_per_approval: 1
phase6_max_open_orders: 1
phase6_max_open_positions: 1
phase6_require_isolated_account: true
hummingbot_v2_leverage: 1
onchain_enabled: false
automatic_scaling: false
```

Local profile files matching `config/*.local.yaml` are ignored by Git.

## 5. Load credentials without placing secrets in files or shell history

```bash
read -rp "Kraken API key: " HIVENANCE_KRAKEN_API_KEY
export HIVENANCE_KRAKEN_API_KEY

read -rsp "Kraken API secret: " HIVENANCE_KRAKEN_API_SECRET
echo
export HIVENANCE_KRAKEN_API_SECRET

export HIVENANCE_PHASE6_LIVE_SUBMISSION=YES
```

Do not paste secrets into logs, screenshots, chat, YAML, JSON or the desktop UI.

## 6. Reconcile before approval

```bash
python scripts/run_phase6_canary.py \
  --profile config/volatility_breakout_phase6.live.local.yaml \
  --reconcile-only
```

Expected state:

```text
status: CLEAN
unknown_orders_count: 0
external open orders: 0
```

Any failure is a stop condition. Do not “try the order anyway.”

## 7. Create the one-entry approval

The exact acknowledgement phrase is mandatory:

```bash
python scripts/run_phase6_canary.py \
  --profile config/volatility_breakout_phase6.live.local.yaml \
  --approve-canary \
  --approved-by "Your Name" \
  --ack-live-risk "I AUTHORIZE ONE TINY LIVE KRAKEN CANARY"
```

The approval expires and can authorize only one entry. It is bound to the current Phase-5 frozen
champion and Phase-6 configuration hash.

## 8. Start the supervised operator process

```bash
python scripts/run_phase6_canary.py \
  --profile config/volatility_breakout_phase6.live.local.yaml \
  --live
```

Live mode deliberately cannot be combined with `--once`.

Keep this process running until:

- the entry is reconciled,
- the local stop, target or horizon exit has completed,
- the exit is reconciled,
- status returns to `DISARMED`,
- no open Phase-6 position remains.

Watch the desktop **Tiny Canary** page or use another terminal:

```bash
python scripts/run_phase6_canary.py \
  --profile config/volatility_breakout_phase6.live.local.yaml \
  --status
```

## 9. Halt and emergency actions

Revoke unused entry authority:

```bash
python scripts/run_phase6_canary.py \
  --profile config/volatility_breakout_phase6.live.local.yaml \
  --revoke-approval \
  --reason "operator decision"
```

Persist a manual HALT:

```bash
python scripts/run_phase6_canary.py \
  --profile config/volatility_breakout_phase6.live.local.yaml \
  --halt \
  --reason "operator decision"
```

Emergency-cancel all open orders on the isolated Kraken account:

```bash
python scripts/run_phase6_canary.py \
  --profile config/volatility_breakout_phase6.live.local.yaml \
  --emergency-cancel-all
```

**Cancel-all does not sell filled spot inventory.** Always reconcile balances and positions after an
emergency cancellation.

## 10. Persistent HALT and recovery

Phase 6 has no automatic resume command. A HALT survives clean reconciliation. Recovery requires:

1. identify and document the incident,
2. reconcile venue orders, fills, balances and local state,
3. ensure no open inventory remains or perform a supervised risk-reducing exit,
4. inspect the Phase-6 incident ledger,
5. create a fresh reviewed release or explicit recovery procedure,
6. issue a new short-lived approval only after the cause is resolved.

Do not edit the SQLite state manually to force `ARMED`.

## 11. Residual risk register

### Local exit supervision

The present canary uses local public-price monitoring for stop, target and horizon exits. The Kraken
dead-man switch cancels stale open orders, but it does not liquidate a filled spot holding. A hard
process or machine failure can therefore leave up to the capped spot notional in the account.

Mitigations:

- maximum entry notional is USD 5,
- no leverage,
- isolated account,
- continuous operator process,
- short polling interval,
- process supervisor recommended,
- immediate reconciliation after restart.

A future hardening step should add venue-native private execution streaming and a verified
server-side protective exit contract before increasing the cap.

### REST polling fidelity

Order state is reconciled through REST. Phase 6 does not yet use Kraken's private execution
WebSocket as the canonical event stream. REST ambiguity causes HALT rather than retry.

### Slippage and stop behaviour

The exit is a marketable IOC limit with a configured slippage ceiling. It can partially fill or fail
in a fast or illiquid market. A stop price is a trigger decision, not a guaranteed execution price.

### API and venue availability

Kraken can reject, delay or restrict orders. System status, instrument status, API-key permissions,
precision, minimum quantity and minimum cost are checked, but no software can guarantee venue
availability.

## 12. Phase-7 evidence gate

The initial review gate requires at least 50 completed and reconciled round trips, no unknown orders,
no unresolved incidents and no open position. Even then:

```text
ready_for_phase7_review: true
execution_scale_authorized: false
automatic_scaling: false
human_review_required: true
```

Do not increase capital because the first canaries happened to make money.
